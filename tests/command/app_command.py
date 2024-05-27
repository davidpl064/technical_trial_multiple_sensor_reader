import argparse
import asyncio

import nats


async def send_command(uri_nats_server: str, app_command: str):
    """Send command action to corresponding topic on NATS server.

    Args:
        uri_nats_server (str): URI of destination NATS server.
        app_command (str): command to be sent.
    """
    nats_client = await nats.connect(uri_nats_server)

    match app_command:
        case "start":
            app_command = str(0)
        case "stop":
            app_command = str(1)
        case "send_config":
            app_command = str(2)
        case "exit":
            app_command = str(3)

    await nats_client.publish("app_command", app_command.encode())
    await nats_client.drain()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app_command", type=str, help="Root directory of the dataset")
    parser.add_argument(
        "--uri_nats_server",
        type=str,
        help="URI of NATS server",
        required=False,
        default="nats://localhost:4222",
    )
    args = parser.parse_args()
    asyncio.run(send_command(args.uri_nats_server, args.app_command))
