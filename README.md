# LifeTime
[LifeTime](http://lifetime.hutei.net/)

## start service
```bash
sudo apt install docker.io
sudo apt install git
git clone https://github.com/VadymHutei/lifetime.git
# run MySQL
# customize config
docker build -t lifetime_app .
docker run --name lifetime_app -d --restart always -p 80:80 lifetime_app
```
