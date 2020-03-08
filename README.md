# LifeTime
[LifeTime](http://lifetime.hutei.net/)

## start service
```bash
sudo apt install docker.io
sudo apt install git
git clone https://github.com/VadymHutei/lifetime.git
cd lifetime
docker build -t lifetime_app .
docker run --name lifetime_app -d --restart always -p 80:80 lifetime_app
```

## update service
```bash
chmod +x ./rebuild.sh
./rebuild.sh
```
