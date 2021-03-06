import shakedown

import sdk_cmd
import sdk_plan
import sdk_utils
import sdk_tasks

PACKAGE_NAME = 'beta-hdfs'
SERVICE_NAME = 'hdfs'

DEFAULT_TASK_COUNT = 10  # 3 data nodes, 3 journal nodes, 2 name nodes, 2 zkfc nodes

TEST_CONTENT_SMALL = "This is some test data"
# use long-read alignments to human chromosome 1 as large file input (11GB)
TEST_CONTENT_LARGE_SOURCE = "http://s3.amazonaws.com/nanopore-human-wgs/chr1.sorted.bam"
TEST_FILE_1_NAME = "test_1"
TEST_FILE_2_NAME = "test_2"
DEFAULT_HDFS_TIMEOUT = 5 * 60
HDFS_POD_TYPES = {"journal", "name", "data"}
DOCKER_IMAGE_NAME = "mesosphere/hdfs-client:2.6.4"
KERBERIZED_CLIENT_IMAGE_NAME = "nvaziri/kerberized-hdfs-client:dev"
KERBERIZED_CLIENT_MEM_SIZE = 512

kerberized_hdfs_client_marathon_app = {
    "id": "hdfsclient",
    "mem": KERBERIZED_CLIENT_MEM_SIZE,
    "container": {
        "type": "MESOS",
        "docker": {
            "image": KERBERIZED_CLIENT_IMAGE_NAME,
            "forcePullImage": True
        },
        "volumes": [
            {
                "containerPath": "/hadoop-2.6.0-cdh5.9.1/hdfs.keytab",
                "secret": "hdfs_keytab"
            }
        ]
    },
    "secrets": {
        "hdfs_keytab": {
            "source": ""
        }
    },
    "networks": [
        {
            "mode": "host"
        }
    ],
    "env": {
        "REALM": "",
        "KDC_ADDRESS": "",
        "JAVA_HOME": "/usr/lib/jvm/default-java",
        "JVM_MaxHeapSize": KERBERIZED_CLIENT_MEM_SIZE
    }
}


def write_data_to_hdfs(service_name, filename, content_to_write=TEST_CONTENT_SMALL):
    write_command = "echo '{}' | ./bin/hdfs dfs -put - /{}".format(content_to_write, filename)
    rc, _ = run_hdfs_command(service_name, write_command)
    # rc being True is effectively it being 0...
    return rc


def read_data_from_hdfs(service_name, filename):
    read_command = "./bin/hdfs dfs -cat /{}".format(filename)
    rc, output = run_hdfs_command(service_name, read_command)
    return rc and output.rstrip() == TEST_CONTENT_SMALL


def delete_data_from_hdfs(service_name, filename):
    delete_command = "./bin/hdfs dfs -rm /{}".format(filename)
    rc, output = run_hdfs_command(service_name, delete_command)
    return rc


def write_lots_of_data_to_hdfs(service_name, filename):
    write_command = "wget {} -qO- | ./bin/hdfs dfs -put /{}".format(TEST_CONTENT_LARGE_SOURCE, filename)
    rc, output = run_hdfs_command(service_name, write_command)
    return rc


def get_active_name_node(service_name):
    name_node_0_status = get_name_node_status(service_name, "name-0-node")
    if name_node_0_status == "active":
        return "name-0-node"

    name_node_1_status = get_name_node_status(service_name, "name-1-node")
    if name_node_1_status == "active":
        return "name-1-node"

    raise Exception("Failed to determine active name node")


def get_name_node_status(service_name, name_node):
    def get_status():
        rc, output = run_hdfs_command(service_name, "./bin/hdfs haadmin -getServiceState {}".format(name_node))
        if not rc:
            return rc

        return output.strip()

    return shakedown.wait_for(lambda: get_status(), timeout_seconds=DEFAULT_HDFS_TIMEOUT)


def run_hdfs_command(service_name, command):
    """
    Execute the command using the Docker client
    """
    full_command = 'docker run -e HDFS_SERVICE_NAME={service_name} {image_name} /bin/bash -c "/configure-hdfs.sh && {cmd}"'.format(
        service_name=service_name,
        image_name=DOCKER_IMAGE_NAME,
        cmd=command
    )

    rc, output = shakedown.run_command_on_master(full_command)
    return rc, output


def check_healthy(service_name, count=DEFAULT_TASK_COUNT, recovery_expected=False):
    sdk_plan.wait_for_completed_deployment(service_name, timeout_seconds=25 * 60)
    if recovery_expected:
        # TODO(elezar): See INFINITY-2109 where we need to better handle recovery health checks
        sdk_plan.wait_for_kicked_off_recovery(service_name, timeout_seconds=25 * 60)
    sdk_plan.wait_for_completed_recovery(service_name, timeout_seconds=25 * 60)
    sdk_tasks.check_running(service_name, count)


def expect_recovery(service_name):
    # TODO(elezar, nima) check_healthy also check for complete deployment, and this should not
    # affect the state of recovery.
    check_healthy(service_name=service_name, count=DEFAULT_TASK_COUNT, recovery_expected=True)


def get_pod_type_instances(pod_type_prefix, service_name=SERVICE_NAME):
    pod_types = sdk_cmd.svc_cli(PACKAGE_NAME, service_name, 'pod list', json=True)
    return [pod_type for pod_type in pod_types if pod_type.startswith(pod_type_prefix)]
