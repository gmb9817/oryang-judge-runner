import sys
import subprocess
import json
import time
import resource
import os
import signal

def handler(event, context):
    """
    AWS Lambda Online Judge Handler
    기능: 소스 코드 컴파일(C++), 실행, 채점, 리소스 측정
    """
    
    # 1. 입력 데이터 파싱 (API Gateway vs 직접 호출 대응)
    if isinstance(event, str):
        body = json.loads(event)
    else:
        body = event

    code = body.get('code', '')
    language = body.get('language', 'python') # 'python' or 'cpp'
    input_data = body.get('input', '')
    
    # 타임아웃 설정 (기본 2초, 요청에 time_limit이 있으면 사용 가능)
    # 안전을 위해 최대 5초를 넘기지 않도록 설정 추천
    time_limit = body.get('time_limit', 2) 

    result = {
        'output': '', 
        'status': 'success',
        'time': 0,    # ms
        'memory': 0   # KB
    }

    # AWS Lambda는 /tmp 디렉토리만 쓰기/실행 권한이 있음
    source_path = ""
    exe_path = ""

    try:
        # ==========================================
        # 1. 컴파일 단계 (C++만 해당)
        # ==========================================
        if language == 'cpp':
            source_path = "/tmp/solution.cpp"
            exe_path = "/tmp/solution"
            
            # 소스 코드 파일 생성
            with open(source_path, "w") as f:
                f.write(code)

            # [핵심] 알고리즘 대회용 국룰 컴파일 옵션
            # -O2: 최적화 레벨 2 (실행 속도 향상)
            # -Wall: 모든 경고 출력
            # -lm: 수학 라이브러리 링크
            # -static: 정적 라이브러리 링크 (호환성 및 보안)
            # -std=gnu++17: C++17 표준 + GNU 확장 기능 (PS 필수)
            compile_cmd = [
                "g++", source_path, 
                "-o", exe_path, 
                "-O2", 
                "-Wall", 
                "-lm", 
                "-static", 
                "-std=gnu++17"
            ]
            
            # 컴파일 실행
            compile_proc = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True
            )

            # 컴파일 에러 체크
            if compile_proc.returncode != 0:
                result['status'] = 'compile_error'
                result['output'] = compile_proc.stderr
                # 컴파일 에러는 즉시 리턴
                return {'statusCode': 200, 'body': json.dumps(result)}

        # ==========================================
        # 2. 실행 단계
        # ==========================================
        
        run_cmd = []
        if language == 'python':
            # 파이썬은 인터프리터로 바로 실행
            run_cmd = [sys.executable, "-c", code]
        elif language == 'cpp':
            # 컴파일된 실행 파일 실행
            run_cmd = [exe_path]

        # 시간 측정 시작
        start_time = time.time()
        
        try:
            process = subprocess.run(
                run_cmd,
                input=input_data,
                capture_output=True,
                text=True,
                timeout=time_limit  # 설정된 시간 제한 적용
            )
            # 정상 종료 혹은 런타임 에러 (Timeout 제외)
            is_timeout = False
            
        except subprocess.TimeoutExpired:
            # 시간 초과 발생
            is_timeout = True
            process = None # 프로세스 정보 없음

        end_time = time.time()

        # ==========================================
        # 3. 결과 분석 및 리소스 측정
        # ==========================================

        if is_timeout:
            result['status'] = 'timeout'
            result['output'] = 'Time Limit Exceeded'
            result['time'] = int(time_limit * 1000) # 제한 시간만큼 기록
        else:
            # 실행 시간 (ms 단위)
            result['time'] = int((end_time - start_time) * 1000)

            # 메모리 사용량 (KB 단위)
            # RUSAGE_CHILDREN: 자식 프로세스의 리소스 사용량
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            result['memory'] = int(usage.ru_maxrss) 

            # 런타임 에러 체크
            if process.returncode != 0:
                result['status'] = 'runtime_error'
                
                # 에러 메시지 처리
                if process.stderr:
                    err_msg = process.stderr.strip()
                    # 너무 긴 에러 메시지는 자름 (1KB)
                    if len(err_msg) > 1024:
                        err_msg = err_msg[:1024] + "\n... (Error truncated)"
                    result['output'] = err_msg
                else:
                    # stderr가 비어있으면 Signal 분석 (Segfault 등)
                    code = -process.returncode # signal은 음수로 반환됨
                    if code == signal.SIGSEGV:
                        result['output'] = "Runtime Error (Segmentation Fault)"
                    elif code == signal.SIGFPE:
                        result['output'] = "Runtime Error (Floating Point Exception)"
                    elif code == signal.SIGABRT:
                        result['output'] = "Runtime Error (Aborted)"
                    else:
                        result['output'] = f"Runtime Error (Exit Code: {process.returncode})"
            else:
                # 정상 실행 (Success)
                output_str = process.stdout.strip() if process.stdout else ""
                
                # 출력 결과 길이 제한 (64KB) - Lambda 응답 크기 초과 방지
                if len(output_str) > 65535:
                    output_str = output_str[:65535] + "\n... (Output truncated)"
                
                result['output'] = output_str

    except Exception as e:
        # 시스템 레벨의 예기치 못한 에러
        result['status'] = 'server_error'
        result['output'] = f"System Error: {str(e)}"
    
    # (선택 사항) 임시 파일 정리
    if os.path.exists(exe_path):
        try: os.remove(exe_path)
        except: pass
    if os.path.exists(source_path):
        try: os.remove(source_path)
        except: pass

    # 최종 결과 반환
    return {
        'statusCode': 200,
        'body': json.dumps(result)
    }
