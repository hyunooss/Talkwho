import sys, time, os, tqdm, torch, argparse, glob, subprocess, warnings, cv2, pickle, numpy, pdb, math, python_speech_features, time

from scipy import signal
from shutil import rmtree
from scipy.io import wavfile
from scipy.interpolate import interp1d

from scenedetect.video_manager import VideoManager
from scenedetect.scene_manager import SceneManager
from scenedetect.frame_timecode import FrameTimecode
from scenedetect.stats_manager import StatsManager
from scenedetect.detectors import ContentDetector

from model.faceDetector.s3fd import S3FD
from ASD import ASD


warnings.filterwarnings("ignore")

video_path = os.path.join(os.pardir, os.pardir, 'media', 'videos')
video_files = sorted(os.listdir(video_path))
video_file = video_files[0].split('.')[0]


parser = argparse.ArgumentParser(description = "Columbia ASD Evaluation")

parser.add_argument('--videoName',             type=str, default=video_file)
parser.add_argument('--videoFolder',           type=str, default=video_path)
parser.add_argument('--ASD_Model',             type=str, default="LightASD.model")

parser.add_argument('--nDataLoaderThread',     type=int,   default=10 )
parser.add_argument('--facedetScale',          type=float, default=0.25, help='face detection scale계수 설정' )
parser.add_argument('--minTrack',              type=int,   default=10 )
parser.add_argument('--numFailedDet',          type=int,   default=10 )
parser.add_argument('--minFaceSize',           type=int,   default=1 )
parser.add_argument('--cropScale',             type=float, default=0.40 )

parser.add_argument('--start',                 type=int, default=0 )
parser.add_argument('--duration',              type=int, default=0 )

args = parser.parse_args()


args.videoPath = glob.glob(os.path.join(args.videoFolder, args.videoName + '.*'))[0]
args.savePath = os.path.join(args.videoFolder, args.videoName)

def scene_detect(args):
	# CPU: 장면 감지, 출력은 각 촬영 시간 기간의 목록
	videoManager = VideoManager([args.videoFilePath])		# 비디오 load. 관리하는데 사용되는 비디오의 경로
	statsManager = StatsManager()							# StatsManager 생성. 비디오의 각 장면에 대한 정보를 추적하는 데 사용
	sceneManager = SceneManager(statsManager)				# StatsManager를 사용하여 장면 관리자를 생성. 장면 감지와 정보 수집을 관리
	sceneManager.add_detector(ContentDetector())			# 컨텐츠 감지기를 추가하여, 장면이 바뀌는 시점을 감지하는 기능을 활성화
	baseTimecode = videoManager.get_base_timecode()			# 비디오의 기본 타임코드를 get. 비디오 시작 시점의 타임코드
	videoManager.set_downscale_factor()						# 비디오의 다운스케일 팩터를 설정. 비디오 처리 속도를 높이기 위해 이미지 해상도를 줄이기 위해 사용
	videoManager.start()									# 비디오 처리를 시작
	sceneManager.detect_scenes(frame_source = videoManager)	# 비디오에서 장면을 감지
	sceneList = sceneManager.get_scene_list(baseTimecode)	# 장면 목록 get. 각 장면은 시작과 끝 타임코드로 표현
	savePath = os.path.join(args.pyworkPath, 'scene.pckl')	# 장면 목록을 저장할 파일의 경로를 설정

	# 만약 감지된 장면이 없다면, 비디오 전체를 하나의 장면으로 취급
	if sceneList == []:
		sceneList = [(videoManager.get_base_timecode(),videoManager.get_current_timecode())]

	# 장면 목록을 파일에 저장.
	with open(savePath, 'wb') as fil:
		pickle.dump(sceneList, fil)
		sys.stderr.write('%s - scenes detected %d\n'%(args.videoFilePath, len(sceneList)))

	# 장면 목록 반환
	return sceneList

def inference_video(args):
	# GPU: Face detection, output is the list contains the face location and score in this frame
	DET = S3FD(device='cuda') 											# GPU를 사용하여 얼굴 감지 모델을 이용
	flist = glob.glob(os.path.join(args.pyframesPath, '*.jpg'))			
	flist.sort()
	dets = []															# 각 프레임의 얼굴 감지 결과를 저장하기 위한 리스트
	for fidx, fname in enumerate(flist):
		image = cv2.imread(fname)										
		imageNumpy = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)				# 이미지를 BGR에서 RGB로 변환.
		bboxes = DET.detect_faces(imageNumpy, conf_th=0.9, scales=[args.facedetScale])		# 감지된 얼굴의 bounding box를 GET
		dets.append([])
		for bbox in bboxes:
		  dets[-1].append({'frame':fidx, 'bbox':(bbox[:-1]).tolist(), 'conf':bbox[-1]}) # 현재 프레임, 경계 상자, 신뢰도 정보를 리스트에 추가
		sys.stderr.write('%s-%05d; %d dets\r' % (args.videoFilePath, fidx, len(dets[-1])))
	savePath = os.path.join(args.pyworkPath,'faces.pckl')				# 필요 없음
	with open(savePath, 'wb') as fil:									# 필요 없음
		pickle.dump(dets, fil)											# 필요 없음
	return dets

def bb_intersection_over_union(boxA, boxB):
	# CPU: # 두 이미지의 겹치는 부분을 계산하는 IOU 함수
	xA = max(boxA[0], boxB[0])
	yA = max(boxA[1], boxB[1])
	xB = min(boxA[2], boxB[2])
	yB = min(boxA[3], boxB[3])
	interArea = max(0, xB - xA) * max(0, yB - yA)
	boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
	boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
	iou = interArea / float(boxAArea + boxBArea - interArea)
	return iou

def track_shot(args, sceneFaces):
	# 얼굴 추적
	iouThres  = 0.5     # 연속된 얼굴 감지 사이의 최소 IOU 값
	tracks    = []		# 추적된 얼굴 트랙을 저장하기 위한 리스트
	while True:
		track     = []	# 현재 추적 중인 얼굴 트랙을 저장하기 위한 리스트
		for frameFaces in sceneFaces:		# 각 프레임에서의 얼굴 감지 결과에 대해 반복
			for face in frameFaces:			# 프레임 내의 각 얼굴에 대해 반복
				# 현재 추적 중인 트랙이 비어 있는 경우 현재 얼굴을 트랙에 추가
				if track == []:				
					track.append(face)		
					frameFaces.remove(face)	# 추가한 얼굴을 현재 프레임에서 제거

				# 이전 얼굴과 현재 얼굴 사이의 프레임 간격이 일정 이하인 경우 IOU를 계산
				elif face['frame'] - track[-1]['frame'] <= args.numFailedDet:			
					iou = bb_intersection_over_union(face['bbox'], track[-1]['bbox'])	
					# IOU가 지정한 임계값보다 큰 경우 현재 얼굴을 트랙에 추가
					if iou > iouThres:			
						track.append(face)		
						frameFaces.remove(face)	# 추가한 얼굴을 현재 프레임에서 제거
						continue
				else:
					break		# 이전 얼굴과 현재 얼굴 사이의 프레임 간격이 지정한 값보다 큰 경우, 더 이상 트랙을 연장 X
		if track == []:			# 더 이상 추적할 얼굴이 없는 경우 반복문 종료
			break				
		elif len(track) > args.minTrack:		# 트랙의 길이가 최소 트랙 길이보다 큰 경우
			frameNum    = numpy.array([ f['frame'] for f in track ])		 	# 트랙 내의 각 얼굴의 프레임 번호를 배열로 저장
			bboxes      = numpy.array([numpy.array(f['bbox']) for f in track])	# 트랙 내의 각 얼굴의 경계 상자 좌표를 배열로 저장
			frameI      = numpy.arange(frameNum[0],frameNum[-1]+1)				# 트랙의 첫 번째 프레임부터 마지막 프레임까지의 프레임 번호 배열을 생성
			bboxesI    = []
			for ij in range(0,4):
				interpfn  = interp1d(frameNum, bboxes[:,ij])		# 트랙 내의 각 좌표 축에 대해 선형 보간 함수를 생성
				bboxesI.append(interpfn(frameI))					# 보간 함수를 사용하여 프레임에 대한 보간된 좌표를 계산하고 리스트에 추가
			bboxesI  = numpy.stack(bboxesI, axis=1)					# 보간된 좌표를 배열로 변환
			if max(numpy.mean(bboxesI[:,2]-bboxesI[:,0]), numpy.mean(bboxesI[:,3]-bboxesI[:,1])) > args.minFaceSize:	# 보간된 좌표 중 가로 또는 세로 길이가 최소 얼굴 크기보다 큰 경우
				tracks.append({'frame':frameI,'bbox':bboxesI})		# 트랙을 추적 목록에 추가
	return tracks		# 추적된 얼굴 트랙을 반환


def crop_video(args, track, cropFile):
	# 얼굴 클립 자르기
	flist = glob.glob(os.path.join(args.pyframesPath, '*.jpg')) # 프레임들을 읽어옴
	flist.sort()
	vOut = cv2.VideoWriter(cropFile + 't.avi', cv2.VideoWriter_fourcc(*'XVID'), 25, (224,224))	# 비디오를 작성하기 위한 객체를 생성
	dets = {'x':[], 'y':[], 's':[]}		# 얼굴 감지 결과를 저장할 딕셔너리를 초기화
	for det in track['bbox']: 
		dets['s'].append(max((det[3]-det[1]), (det[2]-det[0]))/2) 
		dets['y'].append((det[1]+det[3])/2) # y의 중심좌표 계산
		dets['x'].append((det[0]+det[2])/2) # x의 중심좌표 계산
	dets['s'] = signal.medfilt(dets['s'], kernel_size=13) 
	dets['x'] = signal.medfilt(dets['x'], kernel_size=13)
	dets['y'] = signal.medfilt(dets['y'], kernel_size=13)
	for fidx, frame in enumerate(track['frame']):
		cs  = args.cropScale	# 클립을 자를 때 사용할 스케일 값을 GET
		bs  = dets['s'][fidx]   # 감지된 얼굴의 크기
		bsi = int(bs * (1 + 2 * cs))  # 얼굴 클립 주변에 여유 공간을 두기 위해 얼굴 크기를 조정
		image = cv2.imread(flist[frame])	# 프레임을 읽어오기
		frame = numpy.pad(image, ((bsi,bsi), (bsi,bsi), (0, 0)), 'constant', constant_values=(110, 110))	# 이미지 주변에 패딩을 추가
		my  = dets['y'][fidx] + bsi  # 얼굴 bounding box의 중심 좌표 y
		mx  = dets['x'][fidx] + bsi  # 얼굴 bounding box의 중심 좌표 x
		face = frame[int(my-bs):int(my+bs*(1+2*cs)),int(mx-bs*(1+cs)):int(mx+bs*(1+cs))]	# 얼굴 클립을 추출합
		vOut.write(cv2.resize(face, (224, 224)))	
	audioTmp    = cropFile + '.wav'				# 임시 오디오 파일 경로를 설정
	audioStart  = (track['frame'][0]) / 25		# 오디오의 시작 시간을 계산
	audioEnd    = (track['frame'][-1]+1) / 25	# 오디오의 종료 시간을 계산
	vOut.release()			# 비디오 작성 객체를 해제
	command = ("ffmpeg -y -i %s -async 1 -ac 1 -vn -acodec pcm_s16le -ar 16000 -threads %d -ss %.3f -to %.3f %s -loglevel panic" % \
		      (args.audioFilePath, args.nDataLoaderThread, audioStart, audioEnd, audioTmp)) 
	output = subprocess.call(command, shell=True, stdout=None) 
	_, audio = wavfile.read(audioTmp)	# 오디오 파일 LOAD
	command = ("ffmpeg -y -i %st.avi -i %s -threads %d -c:v copy -c:a copy %s.avi -loglevel panic" % \
			  (cropFile, audioTmp, args.nDataLoaderThread, cropFile)) # 오디오와 비디오 파일을 결합
	output = subprocess.call(command, shell=True, stdout=None)
	os.remove(cropFile + 't.avi')	# 임시 비디오 파일을 삭제
	return {'track':track, 'proc_track':dets}	# 추적 정보와 처리된 추적 정보를 반환

def extract_MFCC(file, outPath):
	# mfcc 추출
	sr, audio = wavfile.read(file)
	mfcc = python_speech_features.mfcc(audio,sr) # MFCC를 추출
	featuresPath = os.path.join(outPath, file.split('/')[-1].replace('.wav', '.npy'))	# 특징 파일의 저장 경로를 설정
	numpy.save(featuresPath, mfcc)	# 추출된 MFCC를 특징 파일로 저장


def evaluate_network(files, args):
	# LightASD 모델을 사용한 활성화된 화자 감지
	s = ASD()
	s.loadParameters(args.ASD_Model)	# ASD 모델의 매개변수를 LOAD
	sys.stderr.write("Model %s loaded from previous state! \r\n"%args.ASD_Model)
	s.eval()	# 모델을 평가 모드로 설정
	allScores = []	# 모든 점수를 저장할 리스트
	# durationSet = {1,2,4,6}  # 결과를 더 신뢰할 수 있도록 설정
	durationSet = {1,1,1,2,2,2,3,3,4,5,6} 
	for file in tqdm.tqdm(files, total = len(files)):
		fileName = os.path.splitext(os.path.basename(file))[0] # 오디오와 비디오를 로드
		_, audio = wavfile.read(os.path.join(args.pycropPath, fileName + '.wav'))
		audioFeature = python_speech_features.mfcc(audio, 16000, numcep = 13, winlen = 0.025, winstep = 0.010)
		video = cv2.VideoCapture(os.path.join(args.pycropPath, fileName + '.avi'))
		videoFeature = []
		while video.isOpened():
			ret, frames = video.read()
			if ret == True:
				face = cv2.cvtColor(frames, cv2.COLOR_BGR2GRAY)
				face = cv2.resize(face, (224,224))
				face = face[int(112-(112/2)):int(112+(112/2)), int(112-(112/2)):int(112+(112/2))]
				videoFeature.append(face)
			else:
				break
		video.release()
		videoFeature = numpy.array(videoFeature)
		length = min((audioFeature.shape[0] - audioFeature.shape[0] % 4) / 100, videoFeature.shape[0])
		audioFeature = audioFeature[:int(round(length * 100)),:]
		videoFeature = videoFeature[:int(round(length * 25)),:,:]
		allScore = [] # 모델을 사용한 평가 결과
		for duration in durationSet:
			batchSize = int(math.ceil(length / duration))
			scores = []
			with torch.no_grad():
				for i in range(batchSize):
					inputA = torch.FloatTensor(audioFeature[i * duration * 100:(i+1) * duration * 100,:]).unsqueeze(0).cuda()
					inputV = torch.FloatTensor(videoFeature[i * duration * 25: (i+1) * duration * 25,:,:]).unsqueeze(0).cuda()
					embedA = s.model.forward_audio_frontend(inputA)
					embedV = s.model.forward_visual_frontend(inputV)	
					out = s.model.forward_audio_visual_backend(embedA, embedV)
					score = s.lossAV.forward(out, labels = None)
					scores.extend(score)
			allScore.append(scores)
		allScore = numpy.round((numpy.mean(numpy.array(allScore), axis = 0)), 1).astype(float)
		allScores.append(allScore)	
	return allScores

def visualization(tracks, scores, args):
	# 비디오 형식으로 결과를 시각화합니다.
	flist = glob.glob(os.path.join(args.pyframesPath, '*.jpg'))	
	flist.sort()
	faces = [[] for i in range(len(flist))]		# 각 프레임에 대한 얼굴 정보를 저장할 리스트를 생성
	for tidx, track in enumerate(tracks):
		score = scores[tidx]
		for fidx, frame in enumerate(track['track']['frame'].tolist()):
			s = score[max(fidx - 2, 0): min(fidx + 3, len(score) - 1)] # average smoothing
			s = numpy.mean(s)
			faces[frame].append({'track':tidx, 'score':float(s),'bbox':track['track']['bbox'][fidx],'s':track['proc_track']['s'][fidx], 'x':track['proc_track']['x'][fidx], 'y':track['proc_track']['y'][fidx]})
	firstImage = cv2.imread(flist[0])
	fw = firstImage.shape[1]
	fh = firstImage.shape[0]
	vOut = cv2.VideoWriter(os.path.join(args.pyaviPath, 'video_only.avi'), cv2.VideoWriter_fourcc(*'XVID'), 25, (fw,fh))
	colorDict = {0: 0, 1: 255}
	face_score = [[] for i in range(len(flist))] 	# 각 프레임에 대한 얼굴 점수를 저장할 리스트를 생성
	for fidx, fname in tqdm.tqdm(enumerate(flist), total = len(flist)):
		image = cv2.imread(fname)
		for face in faces[fidx]:
			clr = colorDict[int((face['score'] >= 0))]
			txt = round(face['score'], 1)
			box = face['bbox']
			for tidx, track in enumerate(tracks):
				break_value = False
				for frame in track['track']['frame'].tolist():
					if frame == fidx:
						face_score[frame].append({'frame':frame, 'score':txt, 'bbox': face['bbox'], 'track': tidx})
						break_value = True
						break
				if break_value == True:
					break

			# 임시
			h = abs(box[1] - box[3])
			w = abs(box[2] - box[0])

			# cv2.rectangle(image, (int(box[0]-0.3*w), int(box[1]-0.3*h)), (int(box[2]+0.3*w), int(box[3]+0.3*h)),(clr,0,255-clr),10)		# 얼굴 주변에 1.6배 큰 파란 사각형을 그립니다, 화자가 아닐 시에는 빨간 사각형
			# cv2.rectangle(image, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])),(0,clr,255-clr),10)		# 얼굴 주변에 작은 초록 사각형을 그립니다, 화자가 아닐 시에는 빨간 사각형
			# cv2.putText(image,'%s'%(txt), (int(face['x']-face['s']), int(face['y']-face['s'])), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,clr,255-clr),5)	# 점수를 텍스트로 사각형 위에 표시합니다.
		vOut.write(image)	# 비디오 작성을 위해 이미지를 저장
	vOut.release()			# 비디오 작성을 종료
	savescorePath = os.path.join(args.pyworkPath, 'scoring.pckl')
	with open(savescorePath, 'wb') as fil:      
			pickle.dump(face_score, fil)
	command = ("ffmpeg -y -i %s -i %s -threads %d -c:v copy -c:a copy %s -loglevel panic" % \
		(os.path.join(args.pyaviPath, 'video_only.avi'), os.path.join(args.pyaviPath, 'audio.wav'), \
		args.nDataLoaderThread, os.path.join(args.pyaviPath,'video_out.avi'))) 
	output = subprocess.call(command, shell=True, stdout=None)	# 명령어를 실행하여 비디오와 오디오를 결합



# Main function
def main():
	print("=" * 50)
	print()
	print('Light-ASD 모델 실행 중...')
	print()

	start = time.time()

	# Initialization 
	args.pyaviPath = os.path.join(args.savePath, 'pyavi')
	args.pyframesPath = os.path.join(args.savePath, 'pyframes')
	args.pyworkPath = os.path.join(args.savePath, 'pywork')
	args.pycropPath = os.path.join(args.savePath, 'pycrop')
	if os.path.exists(args.savePath):
		rmtree(args.savePath)
	os.makedirs(args.pyaviPath, exist_ok = True) # 입력 비디오, 입력 오디오, 출력 비디오를 저장할 경로를 생성
	os.makedirs(args.pyframesPath, exist_ok = True) # 모든 비디오 프레임을 저장
	os.makedirs(args.pyworkPath, exist_ok = True) # 이 프로세스의 결과를 저장
	os.makedirs(args.pycropPath, exist_ok = True) # 이 프로세스에서 검출된 얼굴 클립(오디오 + 비디오)을 저장

	# 비디오 추출
	args.videoFilePath = os.path.join(args.pyaviPath, 'video.avi')
	# duration이 설정되지 않은 경우 전체 비디오를 추출하고, 그렇지 않은 경우 'args.start'부터 'args.start + args.duration'까지의 비디오를 추출
	if args.duration == 0:
		command = ("ffmpeg -y -i %s -qscale:v 2 -threads %d -async 1 -r 25 %s -loglevel panic" % \
			(args.videoPath, args.nDataLoaderThread, args.videoFilePath))
	else:
		command = ("ffmpeg -y -i %s -qscale:v 2 -threads %d -ss %.3f -to %.3f -async 1 -r 25 %s -loglevel panic" % \
			(args.videoPath, args.nDataLoaderThread, args.start, args.start + args.duration, args.videoFilePath))
	subprocess.call(command, shell=True, stdout=None)
	sys.stderr.write(time.strftime("%Y-%m-%d %H:%M:%S") + " Extract the video and save in %s \r\n" %(args.videoFilePath))
	
	# 오디오 추출
	args.audioFilePath = os.path.join(args.pyaviPath, 'audio.wav')
	command = ("ffmpeg -y -i %s -qscale:a 0 -ac 1 -vn -threads %d -ar 16000 %s -loglevel panic" % \
		(args.videoFilePath, args.nDataLoaderThread, args.audioFilePath))
	subprocess.call(command, shell=True, stdout=None)
	sys.stderr.write(time.strftime("%Y-%m-%d %H:%M:%S") + " Extract the audio and save in %s \r\n" %(args.audioFilePath))

	# 비디오 프레임 추출
	command = ("ffmpeg -y -i %s -qscale:v 2 -threads %d -f image2 %s -loglevel panic" % \
		(args.videoFilePath, args.nDataLoaderThread, os.path.join(args.pyframesPath, '%06d.jpg'))) 
	subprocess.call(command, shell=True, stdout=None)
	sys.stderr.write(time.strftime("%Y-%m-%d %H:%M:%S") + " Extract the frames and save in %s \r\n" %(args.pyframesPath))

	# 비디오 프레임에 대한 장면 탐지
	scene = scene_detect(args)
	sys.stderr.write(time.strftime("%Y-%m-%d %H:%M:%S") + " Scene detection and save in %s \r\n" %(args.pyworkPath))	

	# 비디오 프레임에 대한 얼굴 탐지
	faces = inference_video(args)
	sys.stderr.write(time.strftime("%Y-%m-%d %H:%M:%S") + " Face detection and save in %s \r\n" %(args.pyworkPath))

	# Face 추적
	allTracks, vidTracks = [], []
	for shot in scene:
		if shot[1].frame_num - shot[0].frame_num >= args.minTrack: # minTrack 프레임보다 작은 shot 프레임은 제외
			allTracks.extend(track_shot(args, faces[shot[0].frame_num:shot[1].frame_num])) # 'frames' : 트랙의 시간 단계, 'bbox' : 얼굴의 위치
	sys.stderr.write(time.strftime("%Y-%m-%d %H:%M:%S") + " Face track and detected %d tracks \r\n" %len(allTracks))

	# Face 클립 자르기
	for ii, track in tqdm.tqdm(enumerate(allTracks), total = len(allTracks)):
		vidTracks.append(crop_video(args, track, os.path.join(args.pycropPath, '%05d'%ii)))
	savePath = os.path.join(args.pyworkPath, 'tracks.pckl')
	with open(savePath, 'wb') as fil:
		pickle.dump(vidTracks, fil)
	sys.stderr.write(time.strftime("%Y-%m-%d %H:%M:%S") + " Face Crop and saved in %s tracks \r\n" %args.pycropPath)
	fil = open(savePath, 'rb')
	vidTracks = pickle.load(fil)

	# 활성화된 화자 감지
	files = glob.glob("%s/*.avi"%args.pycropPath)
	files.sort()
	scores = evaluate_network(files, args)
	savePath = os.path.join(args.pyworkPath, 'scores.pckl')
	with open(savePath, 'wb') as fil:
		pickle.dump(scores, fil)
	sys.stderr.write(time.strftime("%Y-%m-%d %H:%M:%S") + " Scores extracted and saved in %s \r\n" %args.pyworkPath)

	visualization(vidTracks, scores, args)

	end = time.time()

	print()
	print('Light-ASD 모델 실행 완료')
	# print(f"🕒걸린 시간 : { end - start:.2f } sec")
	print()

if __name__ == '__main__':
    main()
