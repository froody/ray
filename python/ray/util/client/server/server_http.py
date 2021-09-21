from ray.util.client.server.server import create_ray_handler
import uvicorn
from fastapi import FastAPI

import os
import uuid
import logging

from ray.util.client.server.background.job_runner import BackgroundJobRunner
from ray.ray_constants import env_integer

import yaml
from ray.experimental.packaging import load_package
from ray._private.runtime_env import working_dir as working_dir_pkg
import ray

logger = logging.getLogger(__name__)

TIMEOUT_FOR_SPECIFIC_SERVER_S = env_integer("TIMEOUT_FOR_SPECIFIC_SERVER_S",
                                            30)
app = FastAPI()


@app.get("/")
async def read_root():
    namespace = f"bg_{str(uuid.uuid4())}"

    actor = BackgroundJobRunner.options(namespace=namespace, lifetime="detached", name="_background_actor").remote()
    actor.run_background_job.remote(
        command="sleep 1 && echo 'hello' && echo 'lmfao' > /tmp/test_file && sleep 100", self_handle=actor
    )

    return {"yoo": "success"}

@app.get("/submit/{yaml_config_path}")
async def submit(yaml_config_path: str):
    # Remote yaml file path on github
    yaml_config_path = "https://raw.githubusercontent.com/ray-project/ray/master/python/ray/experimental/job/example_job/job_config.yaml"
    config_path = load_package._download_from_github_if_needed(yaml_config_path)
    print(f"config_path: {config_path}")

    # config_path = "/Users/jiaodong/Workspace/ray/python/ray/experimental/job/example_job/job_config.yaml"

    config = yaml.safe_load(open(config_path).read())
    runtime_env = config["runtime_env"]
    # working_dir = runtime_env["working_dir"]
    working_dir = os.path.abspath(os.path.dirname(config_path))
    # Uploading working_dir to GCS
    pkg_name = working_dir_pkg.get_project_package_name(
            working_dir=working_dir, py_modules=[], excludes=[])
    pkg_uri = working_dir_pkg.Protocol.GCS.value + "://" + pkg_name

    def do_register_package():
        if not working_dir_pkg.package_exists(pkg_uri):
            tmp_path = os.path.join(load_package._pkg_tmp(), "_tmp{}".format(pkg_name))
            working_dir_pkg.create_project_package(
                working_dir=working_dir,
                py_modules=[],
                excludes=[],
                output_path=tmp_path)
            # Ignore GC for prototype
            working_dir_pkg.push_package(pkg_uri, tmp_path)
            if not working_dir_pkg.package_exists(pkg_uri):
                raise RuntimeError(
                    "Failed to upload package {}".format(pkg_uri))

    if ray.is_initialized():
        do_register_package()
    else:
        ray.worker._post_init_hooks.append(do_register_package)

    runtime_env["uris"] = [pkg_uri]

    print(f"runtime_env: {runtime_env}")

    command = config["command"]

    namespace = f"bg_{str(uuid.uuid4())}"

    actor = BackgroundJobRunner.options(
        namespace=namespace,
        lifetime="detached",
        name="_background_actor").remote()

    job_handle = actor.run_background_job.remote(
        command=command, self_handle=actor, config_path=config_path
    )

    return {"job_handle": str(job_handle)}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Host IP to bind to")
    parser.add_argument(
        "-p", "--port", type=int, default=10011, help="Port to bind to")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["proxy", "legacy", "specific-server"],
        default="proxy")
    parser.add_argument(
        "--redis-address",
        required=False,
        type=str,
        help="Address to use to connect to Ray")
    parser.add_argument(
        "--redis-password",
        required=False,
        type=str,
        help="Password for connecting to Redis")
    parser.add_argument(
        "--worker-shim-pid",
        required=False,
        type=int,
        default=0,
        help="The PID of the process for setup worker runtime env.")
    parser.add_argument(
        "--metrics-agent-port",
        required=False,
        type=int,
        default=0,
        help="The port to use for connecting to the runtime_env agent.")
    args, _ = parser.parse_known_args()
    logging.basicConfig(level="INFO")

    ray_connect_handler = create_ray_handler(args.redis_address,
                                             args.redis_password)

    ray_connect_handler()
    uvicorn.run(app, port=args.port)


if __name__ == "__main__":
    main()