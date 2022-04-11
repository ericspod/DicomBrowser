# Docker file for creating an image to host the viewer. To run this requires an X Windows host with the appropriate
# network open environment setup. To run locally a command like the following will work:
#
#    docker run -ti --rm --net=host -e DISPLAY -v "$HOME/.Xauthority:/root/.Xauthority:rw" dicombrowser
#
# You may have to run "xhost +local:docker" beforehand to allow local connections. 

#FROM alpine:3.14
FROM continuumio/miniconda3:4.10.3p0-alpine

#RUN apk update && apk add py3-qt5 py3-pip ttf-freefont mesa-dri-gallium

RUN apk update && apk add ttf-freefont mesa mesa-dri-gallium glib freeglut

WORKDIR /dicombrowser

COPY . /dicombrowser

RUN pip install .

CMD ["dicombrowser"]
