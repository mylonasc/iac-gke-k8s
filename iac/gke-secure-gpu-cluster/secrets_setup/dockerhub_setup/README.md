## OUTDATED! 
Kept for reference. 

To be deleted after making sure the new setup works fine. 

---------------------------

## Setting up the docker hub token for k8s use:
Dockerhub expects the PAT in the following format in a file called `.dockerconfigjson`.  
```python
{
  "auths": {
    "https://index.docker.io/v1/": {
      "username": "<your-dockerhub-username>",
      "password": "<your-personal-access-token>",
      "email": "<your-email>",
      "auth": "BASE64_ENCODED_USERNAME:PASSWORD"
    }
  }
}
```

You can use the following command (with the provided script) to generate this: 

```bash
./01_make_dockerconfig.sh mylonasc $(cat ~/Workspace/secrets/docker-hub-read-only-pat) mylonas.charilaos@gmail.com > docker.json
```

and subsequently, run 
```bash
cat docker.json | base64 > docker_secret.bs64
./02_add_dockerhub_secret.sh
```

which adds the dockerhub secret to google secrets manager. 



