import asyncio
import functools
import logging
import json
from pprint import pprint, pformat

from utility import ToolError

END_OF_MESSAGE = b"\4"
END_OF_CHUNK = b"\27"
END_MESSAGE_CHUNK = b"\4\27"


logger = logging.getLogger(__name__)

async def handle_message(writer, queue):
    try:
        while True:
            item = await queue.get()

            logger.info(f'received message {item}')
            msg = {
                'type': 'message',
                'content': item
            }
            writer.write(bytes(json.dumps(msg), "utf8") + END_MESSAGE_CHUNK)
            await writer.drain()
    except Exception as e:
        logger.critical('This happens')
        logger.critical(e.with_traceback)
        logger.critical(e)


async def handle_request(reader, writer, callback, debug: bool = False):
    # "\4" (oct) ascii: end of transmission
    while True:
        try:
            # data = await reader.read(16384)
            # chunks end with \23 (end of transmission block)
            # complete message ends with \4\23 (end of transmission / end of transmission block)
            data = (await reader.readuntil(END_OF_CHUNK))
            while not data.endswith(END_MESSAGE_CHUNK):
                logger.info("waiting for data")
                data = data.rstrip(END_OF_CHUNK)
                data += (await reader.readuntil(END_OF_CHUNK))
            data = data.rstrip(END_MESSAGE_CHUNK)
            if not data:
                break
            try:
                json_data = json.loads(data)
            except Exception as e:
                logger.error(e)
                logger.error(f"Could not parse: {data}")
                continue
            log_level = json_data.get('log_level', logging.INFO)
            logger.log(log_level, pformat(json_data, indent=4))
            try:
                result = callback(json_data)
            except ToolError as e:
                logger.info(f"Tool Error: {e}")
                writer.write(bytes(json.dumps({'type': 'return', 'error': str(e), "error_type": str(type(e)), "tool_error": True}), "utf8") + END_MESSAGE_CHUNK)
            except Exception as e:
                logger.info(f"{type(e)}: {e}")
                logger.error(e)
                writer.write(bytes(json.dumps({'type': 'return', 'error': str(e), "error_type": str(type(e))}), "utf8") + END_MESSAGE_CHUNK)
                if debug:
                    raise
            else:
                res = pformat(result, indent=4)
                if len(res) > 103:
                    res = pformat(result, indent=4)[:100] + "..."
                logger.log(log_level, f"Return: {res}")
                result = bytes(result, "utf8")
                step = 2**14

                writer.write(END_OF_CHUNK.join(result[chunk: chunk + step] for chunk in range(0, len(result), step)) + END_MESSAGE_CHUNK)

            await writer.drain()
        except Exception as e:
            logger.critical(e)
            raise e


async def handle_connection(reader, writer, callback, msg_queue, debug: bool):
    logger.info(f"New connection! {writer.get_extra_info('peername')}")
    my_queue = asyncio.Queue()
    msg_queue.new_queue(my_queue)
    await asyncio.gather(handle_request(reader, writer, callback), handle_message(writer, my_queue))
    # await asyncio.wait([asyncio.Task(handle_request(reader, writer, callback)), asyncio.Task(handle_message(writer, my_queue))], return_when=asyncio.FIRST_EXCEPTION)
    msg_queue.remove_queue(my_queue)


async def run_server(callback, message_queue, host="", port: int=8002, debug: bool = False):

    server = await asyncio.start_server(functools.partial(handle_connection, callback=callback, msg_queue=message_queue, debug=debug), host, port)
    logger.info(f"Server hört auf {host or 'alle'}:{port}")
    async with server:
        await server.serve_forever()
    return
