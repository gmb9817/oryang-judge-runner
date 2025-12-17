FROM public.ecr.aws/lambda/python:3.11

# gcc, g++ 설치 (필수!)
RUN yum update -y && \
    yum install -y gcc gcc-c++ && \
    yum clean all

# 코드 복사
COPY lambda_function.py ${LAMBDA_TASK_ROOT}

# 핸들러 설정
CMD [ "lambda_function.lambda_handler" ]
