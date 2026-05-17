FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

RUN sed -i 's|http://archive.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g; s|http://security.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list

RUN apt-get update \
 && apt-get install -y --no-install-recommends socat gcc libc6-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /usr/share/doc/* /usr/share/man/* 

COPY main.c /main.c
COPY flag.txt /flag.txt
COPY flag16.txt /flag16.txt
RUN gcc /main.c -o /main -no-pie -fno-pic -fno-stack-protector -z execstack \
 && rm -f /main.c \
 && chmod 755 /main \
 && chown nobody:nogroup /main /flag.txt /flag16.txt

USER nobody:nogroup

EXPOSE 31337

ENTRYPOINT ["socat","tcp-l:31337,reuseaddr,fork","exec:/main"]
