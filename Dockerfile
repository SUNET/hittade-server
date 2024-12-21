FROM python:3.11
ENV PYTHONUNBUFFERED=1
WORKDIR /code
COPY .docker/ /code/.docker/
RUN bash .docker/scripts/setup-sass.sh
COPY requirements-dev.txt /code/
RUN pip install -r requirements-dev.txt
COPY . /code/
