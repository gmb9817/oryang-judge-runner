FROM public.ecr.aws/lambda/python:3.11

RUN yum update -y && \
    yum install -y gcc-c++ make && \
    yum clean all

WORKDIR ${LAMBDA_TASK_ROOT}

COPY lambda_function.py .

CMD [ "lambda_function.handler" ]
