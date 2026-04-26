import os
import boto3
from urllib import request
from urllib.parse import urlparse
import argparse
import time
from datetime import datetime

class Transcriber:
    def __init__(self, access_key, secret_key, region, bucket_name, video_name):
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.bucket_name = bucket_name
        self.video_name = video_name
        self.transcribe = boto3.client(
            'transcribe',
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
    
    def upload_to_s3(self, video_path):
        '''S3 버킷에 비디오 파일 업로드'''
        s3 = boto3.resource(
            's3',
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region
        )
        bucket = s3.Bucket(self.bucket_name)
        bucket.upload_file(video_path, self.video_name)
    
    def generate_url(self, bucket):
        '''업로드된 비디오 파일의 URL 생성'''
        video_url = bucket.Object(self.video_name).meta.client.generate_presigned_url(
            'get_object', Params={'Bucket': self.bucket_name, 'Key': self.video_name}, ExpiresIn=3600)
        return urlparse(video_url)
    
    def start_transcribe_job(self, job_uri, file_ex):
        '''Transcribe 작업 시작'''
        now = datetime.now()
        now_str = now.strftime("%Y%m%d%H%M%S")
        self.job_name = self.video_name + "_" + now_str
        
        self.transcribe.start_transcription_job(
            TranscriptionJobName=self.job_name,
            Media={'MediaFileUri': job_uri},
            MediaFormat=file_ex,
            IdentifyMultipleLanguages=True,
            Settings={
                'ShowSpeakerLabels': True,  # 화자분리 기능 True or False
                'MaxSpeakerLabels': 3  # 화자수
            },
            Subtitles={
                'Formats': ['vtt','srt'],
                'OutputStartIndex': 1
            }
        )
    
    def wait_for_job_to_finish(self):
        '''Transcribe 작업 완료를 기다린 후 결과를 가져옴'''
        while True:
            status = self.transcribe.get_transcription_job(TranscriptionJobName=self.job_name)
            if status['TranscriptionJob']['TranscriptionJobStatus'] in ['COMPLETED', 'FAILED']:
                save_stt_uri = status['TranscriptionJob']['Subtitles']['SubtitleFileUris'][1]
                break
        return save_stt_uri
    
    def download_result_and_save_to_file(self, save_stt_uri, output_file_path):
        '''결과를 다운로드하여 SRT 파일로 저장'''
        with request.urlopen(save_stt_uri) as f:
            result = f.read().decode('utf-8')
        
        with open(output_file_path, 'w') as f:
            f.write(result)
    
    def delete_file_from_s3(self):
        '''S3 버킷에서 비디오 파일 삭제'''
        s3 = boto3.resource(
            's3',
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region
        )
        s3.Object(self.bucket_name, self.video_name).delete()

def main():
    print("=" * 50)
    print()
    print('Whisper STT 실행 중...')
    print()

    start = time.time()
    
    # AWS 인증을 위한 키와 지역 설정
    access_key="key"
    secret_key="key"
    region = "key"

    # 동영상을 업로드할 S3 버킷 이름
    bucket_name = 'ket'

    # 로컬에서 동영상 파일이 위치한 폴더 경로
    file_dir = os.path.join(os.pardir, 'media', 'videos')

    # argparse를 사용하여 동영상 파일 이름을 입력으로 받음
    parser = argparse.ArgumentParser(description = "video Name")
    parser.add_argument('--videoName', type=str, default='exam')
    args = parser.parse_args()
    video_name = args.videoName
    file_nm = args.videoName.split('.')[0]
    file_ex = args.videoName.split('.')[1]

    # 동영상 파일의 전체 경로
    video_path = os.path.join(file_dir, video_name)

    transcriber = Transcriber(access_key, secret_key, region, bucket_name, video_name)

    transcriber.upload_to_s3(video_path)
    job_uri = f's3://{bucket_name}/{video_name}'
    transcriber.start_transcribe_job(job_uri, file_ex)
    save_stt_uri = transcriber.wait_for_job_to_finish()

    output_file_path = "../media/srt/subtitles_out.srt"
    output_file_path = f"../media/srt/{file_nm}.srt"
    transcriber.download_result_and_save_to_file(save_stt_uri, output_file_path)
    transcriber.delete_file_from_s3()

    end = time.time()

    print('Whisper STT 실행 완료')
    # print(f"🕒걸린 시간 : {end - start:.2f} sec")
    print()

if __name__ == "__main__":
    main()