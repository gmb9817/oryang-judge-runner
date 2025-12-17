FROM public.ecr.aws/lambda/python:3.11

# 1. 필수 패키지 및 다운로드 도구 설치
RUN yum update -y && \
    yum install -y gcc gcc-c++ tar gzip wget bzip2 && \
    yum clean all

# 2. PyPy 3.10 (Linux x64) 다운로드 및 설치
# (버전은 호환성을 위해 3.10 v7.3.16 사용, 필요시 최신 버전 URL로 교체 가능)
RUN wget https://downloads.python.org/pypy/pypy3.10-v7.3.16-linux64.tar.bz2 -O /tmp/pypy.tar.bz2 && \
    tar -xjf /tmp/pypy.tar.bz2 -C /opt && \
    mv /opt/pypy3.10-v7.3.16-linux64 /opt/pypy && \
    ln -s /opt/pypy/bin/pypy3 /usr/bin/pypy3 && \
    rm -rf /tmp/pypy.tar.bz2

# 3. 코드 복사
COPY lambda_function.py ${LAMBDA_TASK_ROOT}

# 4. 핸들러 설정
CMD [ "lambda_function.lambda_handler" ]
