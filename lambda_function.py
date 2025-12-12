import sys
import subprocess
import json
import time
import resource  # 리눅스 리소스 사용량 측정 모듈

def handler(event, context):
    """
    AWS Lambda 진입점
    """
    # 입력 데이터 파싱
    if isinstance(event, str):
        body = json.loads(event)
    else:
        body = event

    code = body.get('code', '')
    language = body.get('language', 'python')
    input_data = body.get('input', '')

    result = {
        'output': '', 
        'status': 'success',
        'time': 0,    # ms 단위
        'memory': 0   # KB 단위
    }

    try:
        # 시작 시간 측정
        start_time = time.time()

        if language == 'python':
            # 파이썬 실행
            process = subprocess.run(
                [sys.executable, "-c", code],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=2 # 2초 제한 (내부 측정용)
            )
            
            # 결과 저장
            if process.returncode != 0:
                result['status'] = 'runtime_error'
                result['output'] = process.stderr
            else:
                result['output'] = process.stdout.strip()

        elif language == 'cpp':
            # C++ 소스 저장
            source_path = "/tmp/solution.cpp"
            exe_path = "/tmp/solution"

            with open(source_path, "w") as f:
                f.write(code)

            # 컴파일 (시간 측정 제외: 컴파일 시간은 채점 시간에 포함 안 함)
            compile_start = time.time()
            compile_proc = subprocess.run(
                ["g++", source_path, "-o", exe_path],
                capture_output=True,
                text=True
            )
            # 컴파일에 걸린 시간은 실행 시간 측정에서 빼기 위해 기록
            compile_offset = time.time() - compile_start

            if compile_proc.returncode != 0:
                result['status'] = 'compile_error'
                result['output'] = compile_proc.stderr
                return {'statusCode': 200, 'body': json.dumps(result)}

            # 실행 (여기서부터 진짜 시간 측정)
            # start_time을 재설정 (컴파일 시간 제외)
            start_time = time.time()
            
            process = subprocess.run(
                [exe_path],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if process.returncode != 0:
                result['status'] = 'runtime_error'
                result['output'] = process.stderr
            else:
                result['output'] = process.stdout.strip()

        # 종료 시간 측정
        end_time = time.time()
        
        # 1. 실행 시간 계산 (ms 단위)
        # 소수점 버림 (int)
        result['time'] = int((end_time - start_time) * 1000)

        # 2. 메모리 사용량 계산 (KB 단위)
        # resource.RUSAGE_CHILDREN: 자식 프로세스(실행된 코드)의 리소스 확인
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        # ru_maxrss: 리눅스에서는 KB 단위로 반환됨
        result['memory'] = int(usage.ru_maxrss)

    except subprocess.TimeoutExpired:
        result['status'] = 'timeout'
        result['output'] = 'Time Limit Exceeded'
        result['time'] = 2000 # 타임아웃이면 최대 시간으로 기록
        
    except Exception as e:
        result['status'] = 'server_error'
        result['output'] = str(e)

    return {
        'statusCode': 200,
        'body': json.dumps(result)
    }
