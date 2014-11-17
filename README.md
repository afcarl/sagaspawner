# SagaSpawner

Enables [JupyterHub](https://github.com/jupyter/jupyterhub) to spawn
user servers a supercomputer computing nodes via PBS or similar queue systems using [SAGA](https://github.com/radical-cybertools/saga-python)

## Setup

Install dependencies:

    pip install -r requirements.txt

Tell JupyterHub to use DockerSpawner, by adding the following to your `jupyter_hub_config.py`:

    c.JupyterHubApp.spawner_class='sagaspawner.SagaSpawner'
