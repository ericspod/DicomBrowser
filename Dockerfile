# Docker file for creating an image to host the viewer. To run this requires an X Windows host with the appropriate
# network open environment setup. To run locally a command like the following will work:
#
#    docker run -ti --rm --net=host --env="DISPLAY" --volume="$HOME/.Xauthority:/root/.Xauthority:rw" dicombrowser

FROM ubuntu:16.04

RUN apt update
RUN apt install x11-apps libgl1-mesa-glx qt5-default libxrandr2 wget -y --fix-missing

RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
RUN /bin/bash Miniconda3-latest-Linux-x86_64.sh -b -p /miniconda3
RUN echo "export PATH=/miniconda3/bin:$PATH" > /root/.bashrc

WORKDIR /DicomBrowser

COPY . /DicomBrowser

RUN /miniconda3/bin/conda install pyqt numpy 

CMD ["/miniconda3/bin/python","-m","DicomBrowser"]