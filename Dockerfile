# Docker file for creating an image to host the viewer. To run this requires an X Windows host with the appropriate
# network open environment setup. To run locally a command like the following will work:
#
#    docker run -ti --rm --net=host -e DISPLAY -v "$HOME/.Xauthority:/root/.Xauthority:rw" dicombrowser
#
# You may have to run "xhost +local:docker" beforehand to allow local connections. 

FROM alpine:3.14

RUN apk update && apk add py3-qt5 py3-numpy py3-pip py3-pillow ttf-freefont mesa-dri-gallium

RUN pip3 install pydicom pyqtgraph

WORKDIR /dicombrowser

COPY . /dicombrowser

CMD ["python3", "-m", "dicombrowser"]
