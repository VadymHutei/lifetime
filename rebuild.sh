#!/bin/bash

docker stop lifetime_app
docker rm lifetime_app
docker rmi lifetime_app
git pull origin master
docker build -t lifetime_app .
docker run --name lifetime_app -d --restart always -p 80:80 lifetime_app
