# Docker file for creating an image to host the viewer. To run this requires an X Windows host with the appropriate
# network open environment setup. To run locally a command like the following will work:
#
#    docker run -ti --rm --net=host --env="DISPLAY" --volume="$HOME/.Xauthority:/root/.Xauthority:rw" dicombrowser


FROM alpine:3.12

RUN apk update
RUN apk add py3-qt5 py3-numpy py3-pip ttf-ubuntu-font-family

RUN pip3 install pydicom pyqtgraph

WORKDIR /dicombrowser

COPY . /bicombrowser

CMD ["python3","-m","dicombrowser"]
