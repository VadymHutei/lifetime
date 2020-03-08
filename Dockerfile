FROM tiangolo/uwsgi-nginx-flask:python3.7

ENV TZ Europe/Kiev
ENV STATIC_URL /static

COPY ./app /app

ADD ./nginx1.conf /etc/nginx/conf.d/

RUN pip install --upgrade pip
RUN pip install -r requirements.txt
