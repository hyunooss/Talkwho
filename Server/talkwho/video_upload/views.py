from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from moviepy.editor import VideoFileClip
from .models import Video
import subprocess
import os
import shutil 
import tempfile
import json
import shutil
import time


# 상수로 설정된 경로와 파일 이름
ASD_CWD = os.path.join('video_upload', 'Light-ASD')
MAIN_CWD = os.path.join('video_upload')
PY_ASD = 'run_ASD.py'
PY_STT = 'stt_whisper.py'   #'stt_aws.py'
PY_SBS = 'subtitle_sync.py'
PY_MER = 'merge_video.py'


def convert_avi_to_mp4(name):
    """
    AVI 파일을 MP4 파일로 변환
    """
    file_name = name.split('.')[0]
    clip = VideoFileClip(f"media/videos/{name}")
    clip.write_videofile(f"media/videos/{file_name}.mp4")
    os.remove(f"media/videos/{name}")
    print('avi -> mp4 변환 성공')
    return f"{file_name}.mp4"


def run_subprocess_1(name, target = 'ko'):
    """
    ASD, STT, SBS를 실행
    """
    subprocess.run(['python', PY_ASD, '--videoName', name.split('.')[0]], cwd=ASD_CWD)             # ASD 실행
    subprocess.run(['python', PY_STT, '--videoName', name], cwd=MAIN_CWD)                          # STT 실행
    subprocess.run(['python', PY_SBS, '--videoName', name, '--language', target], cwd=MAIN_CWD)    # Subtitle Sync 실행
    
    # zip 파일 생성 (pyframe, json)
    make_archive(name.split('.')[0])    


def run_subprocess_2(name, target='ko'):
    """
    Merge video를 실행
    """
    subprocess.run(['python', PY_MER, '--videoName', name, '--language', target], cwd=MAIN_CWD)    


def make_archive(file_name):
    """
    지정된 디렉토리 및 파일을 압축하여 하나의 zip 파일로 생성
    """
    print("=" * 50)
    print()
    print('make_archive 실행 중...')
    JSON_OUT_PATH = os.path.join('media', 'mid_json', f'{file_name}.json')
    PYFRAME_PATH = os.path.join('media', 'videos', f'{file_name}','pyframes')

    with tempfile.TemporaryDirectory() as temp_dir:
        # 디렉터리와 파일을 임시 디렉터리에 복사
        shutil.copytree(PYFRAME_PATH, os.path.join(temp_dir, 'pyframe'))
        shutil.copy(JSON_OUT_PATH, os.path.join(temp_dir, f'{file_name}.json'))

        # 이제 임시 디렉터리에서 zip 아카이브를 생성
        output_filename = os.path.join('media', 'mid_zip', file_name)
        shutil.make_archive(output_filename, 'zip', temp_dir)
    print('make_archive 실행 완료')
    print()


def delete_files(name):
    """
    클라이언트로 response 후 생성된 파일들을 삭제
    """
    files_to_delete = [
        f'media/fin_json/{name}_out.json',
        f'media/mid_json/{name}.json',
        f'media/mid_zip/{name}.zip',
        f'media/result/{name}_output.mp4',
        f'media/srt/{name}.srt',
        f'media/videos/{name}',
        f'media/videos/{name}.mp4'
    ]
    for file_path in files_to_delete:
        try:
            if os.path.isfile(file_path):   # 파일이면
                os.remove(file_path)
                print(f'Successfully deleted {file_path}')
            elif os.path.isdir(file_path):  # 디렉토리면
                shutil.rmtree(file_path)
                print(f'Successfully deleted directory {file_path}')
            else:
                print(f'Error: {file_path} not found')
        except Exception as e:
            print(f'Error deleting {file_path}: {str(e)}')
    
@csrf_exempt
def upload(request):
    """
    파일을 업로드하고, 필요한 경우 파일 형식을 변환하고 ASD, STT를 실행
    """
    if request.method == 'POST':
        print("☘️" * 8)
        print('☘️ Request ok ☘️')
        print("☘️" * 8)
        

        # 파일 저장
        start = time.time()
        Video.objects.create(file=request.FILES['video'])
        end = time.time()
        print(f"Time to receive videos  : {end - start:.2f} sec")

        name = request.FILES['video'].name
        target = request.POST['language']

        # session으로 저장
        # request.session['name'] = name
        # request.session['target'] = target
        # print(f"sessin_name = {request.session.get('name')}")
        # print(f"sessin_target = {request.session.get('target')}")

        # video.text로 저장
        with open(f"media/video.text", 'w', encoding='utf-8') as file:
            file.write(f"{name}\n")
            file.write(f"{target}")


        print()
        print('Input Video : ', name)
        print('Input Target : ', target)
        print()
        

        # 파일 확장자 확인
        file_extension = name.split('.')[1]
        if file_extension == 'mkv':             # AVI 파일이면 MP4로 변환
            name = convert_avi_to_mp4(name)


        # ASD, STT, SBS, ZIP 실행
        run_subprocess_1(name, target)   


        file_path = os.path.join('media', 'mid_zip', f"{name.split('.')[0]}.zip")
        if os.path.exists(file_path):
            # json으로 response
            download_url = request.build_absolute_uri(f'/media/mid_zip/{name.split(".")[0]}.zip')
            print("☘️" * 12)
            print('☘️ archive  전송 완료 ☘️')
            print("☘️" * 12)
            print()
            
            return JsonResponse({'data': {'url': download_url}})

    # POST가 아닐 때
    return render(request, 'upload.html')


@csrf_exempt
def edit(request):
    """
    수정된 JSON 파일을 받아서 MER 실행후 결과 파일을 전송
    """
    if request.method == 'POST':
        print("🌸" * 8)
        print('🌸 Request ok 🌸')
        print("🌸" * 8)

        # request body에서 json 데이터를 load
        json_data = json.loads(request.body)

        # session으로 저장했을 때
        # name = request.session.get('name')
        # target = request.session.get('target')
        # print(f'name : {name}')
        # print(f'target : {target}')

        # video.text로 저장했을 때
        with open(f"media/video.text", 'r', encoding='utf-8') as file:
            lines = file.readlines()
            name = lines[0]
            target = lines[1]
            

        with open(f"media/video.text", 'w', encoding='utf-8') as file:
            file.write('')


        # # json 데이터 저장
        with open(f"media/fin_json/{name.split('.')[0]}_out.json", "w") as f:
            json.dump(json_data, f, indent = 4)


        # Merge video 실행
        run_subprocess_2(name, target)
        
        download_url = request.build_absolute_uri(f'/media/result/{name.split(".")[0]}_output.mp4')
        # download_url = request.build_absolute_uri(f'/media/result/baek_result.mp4')

        print("🌸" * 12)
        print('🌸  Result 전송 완료  🌸')
        print("🌸" * 12)


        # 1. 파일 삭제 안하고 Response
        return JsonResponse({'data': {'url': download_url}})
        

        # 2. 파일 삭제 후 Response
        try:
            return JsonResponse({'data': {'url': download_url}})
        finally:
            delete_files(name.split('.')[0])


    # test용 GET
    # else:
    #     # name = request.FILES['video'].name
    #     name = request.session.get('name')
    #     target = request.session.get('target')
    #     print(name)
    #     print(target)
    #     output_path = os.path.join('media', 'result', "quiz_output.mp4")
    #     output_path = 'media/result/quiz_output.mp4'
    #     download_url = request.build_absolute_uri(f'/media/result/quiz_output.mp4')
    #     return JsonResponse({'download_url': download_url})


# ------------------- test ------------------------------

@csrf_exempt
def test(request):
    if request.method == 'POST':
        # target = request.POST['myText']
        data = json.loads(request.body)
        target = data.get('myText')
        print(type(target))
    return HttpResponse('OK')

@csrf_exempt
def test2(request):
    if request.method == 'POST':
        # 파일 저장
        print('Request ok')
        start = time.time()

        Video.objects.create(file=request.FILES['video'])
        name = request.FILES['video'].name
        # target = request.POST['language']
        print()
        print('Input Video : ', name)
        # print('Input Target : ', target)

        end = time.time()

        print(f"동영상 받는 시간 : {end - start:.5f} sec")
    return HttpResponse('OK')