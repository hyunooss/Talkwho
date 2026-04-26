### 영상과 자막을 합치는 코드


from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
from moviepy.video.tools.subtitles import SubtitlesClip
import json
import argparse
import os
import time

from moviepy.config import change_settings
change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\\magick.exe"})

print("=" * 50)
print()
print('merge_video 실행 중...')
startT = time.time()


# argparse를 사용하여 동영상 파일 이름을 입력으로 받음
parser = argparse.ArgumentParser(description = "video Name")
parser.add_argument('--videoName', type=str, default='001')    # 비디오 이름
parser.add_argument('--language', type=str, default='ko')     # 타겟 언어
args = parser.parse_args()
file_nm = args.videoName.split('.')[0]

# 자막을 배치
if args.language == 'ko':
    font = 'Malgun-Gothic'
    print('target : ko')
else:
    font = 'Arial-Unicode-MS'
    print('target : en')

# 동영상 파일 경로
video_path = os.path.join(os.pardir, 'media', 'videos', file_nm , 'pyavi', 'video_out.avi')
# 동영상 로드
video = VideoFileClip(video_path)
# json 파일 
subtitles_json = os.path.join(os.pardir, 'media', 'fin_json', f'{file_nm}_out.json')


with open(subtitles_json) as f:
    subtitles = json.load(f)

subs = subtitles['data']
subtitles_clip = []
subtitles_clip2 = []

for sub in subs:
    text_clip = (
        TextClip(sub['text'], fontsize=24, color='white', font=font, stroke_color='black', stroke_width=3)
        .set_position(sub['pos'])
        .set_start(sub['start_time'])
        .set_end(sub['end_time'])
    )
    text_clip2 = (
        TextClip(sub['text'], fontsize=24, color='white', font=font)
        .set_position(sub['pos'])
        .set_start(sub['start_time'])
        .set_end(sub['end_time'])
    )
    subtitles_clip.append(text_clip)
    subtitles_clip2.append(text_clip2)

subtitles_clip.append(text_clip)# 텍스트 클립들을 동영상 위에 합성
video_with_text = CompositeVideoClip([video] + subtitles_clip + subtitles_clip2)


# 합성된 동영상을 저장
output_path = os.path.join(os.pardir, 'media', 'result', f'{file_nm}_output.mp4')
video_with_text.write_videofile(output_path, 
                                codec='libx264', 
                                audio_codec='aac'
                                # temp_audiofile='temp-audio.m4a',  # 임시 오디오 파일 경로 지정
                                # remove_temp=True,  # 임시 파일 삭제
                                # threads=4,  # 병렬 처리를 위한 스레드 수
                                # preset='ultrafast',  # 인코딩 속도 개선
                                )

end = time.time()
print('merge_movie 실행 완료')
# print(f"🕒걸린 시간 : {end - startT:.2f} sec")
print("=" * 50)
print()
print('(❁´◡`❁) 성공적으로 자막을 생성했습니다. (❁´◡`❁)')
print()
