#!/bin/bash

docker stop lifetime_app
docker rm lifetime_app
docker rmi lifetime_app

docker stop mysql
docker rm mysql

git pull origin master

docker build -t lifetime_app .
docker run --name lifetime_app -d --restart always -p 80:80 lifetime_app

docker run --name mysql -d --restart always -v /home/mysql_data:/var/lib/mysql -e MYSQL_ROOT_PASSWORD=root -p 3306:3306 mysql:5
