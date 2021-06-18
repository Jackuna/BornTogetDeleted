FROM python:3.8-slim
LABEL maintainer="Jackuna (github.com/jackuna)"

RUN apt-get update
RUN pip --version
RUN pip install paramiko boto3
RUN apt-get install git -y

WORKDIR /usr/local/
RUN git clone https://github.com/Jackuna/BornTogetDeleted.git

WORKDIR /usr/local/BornTogetDeleted
