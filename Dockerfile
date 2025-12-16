FROM public.ecr.aws/lambda/python:3.11

RUN dnf update -y && \
    dnf install -y gcc-c++ make binutils glibc-devel libstdc++-devel && \
    dnf clean all

WORKDIR ${LAMBDA_TASK_ROOT}

COPY lambda_function.py .

CMD [ "lambda_function.handler" ]
