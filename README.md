# lifetime

## install docker
```bash
sudo apt install docker.io
```

## create and run container
```bash
docker build -t lifetime_app .
docker run --name lifetime_app -d --restart always -p 80:80 lifetime_app
```
