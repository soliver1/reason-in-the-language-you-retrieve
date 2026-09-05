import enum
import logging
import asyncio
import json
from asyncio import IncompleteReadError
from collections import namedtuple

logger = logging.getLogger(__name__)

END_OF_MESSAGE = b"\4"
END_OF_CHUNK = b"\27"
END_MESSAGE_CHUNK = b"\4\27"

ErrorResponse = namedtuple("ErrorResponse", ["message", "type"])

class ConnectionManagerException(Exception):
    """Base class for exceptions in this module."""
    def __init__(self, error_message: str, error_type: str):
        self.error_message = error_message
        self.error_type = error_type

class ConnectionManagerError(ConnectionManagerException):
    pass

class ConnectionManagerComplaint(ConnectionManagerException):
    pass


class ReturnType(enum.Enum):
    SUCCESS = enum.auto()
    COMPLAINT = enum.auto()
    ERROR = enum.auto()
    CONNECTION_CLOSED = enum.auto()

class ConnectionManager:
    def __init__(self, address, port, storage):
        self.address = address
        self.port = port
        self._con_lock = asyncio.Lock()
        self._response = asyncio.Queue(1)
        self._reader = None
        self._writer = None
        self.storage = storage

        self._watch_task = None

    async def connect(self):
        await self._connect()
        self._watch_task = asyncio.create_task(self.watch())

    async def _connect(self):
        waiting = 2
        while True:
            try:
                self._reader, self._writer = await asyncio.open_connection(
                    self.address, self.port
                )
            except ConnectionError:
                await asyncio.sleep(min(waiting, 8))
                waiting *= 2
                logger.warning("Server not found. trying again....")
            else:
                break

    async def watch(self):
        try:
            while True:
                # result = await self._reader.read(2**20)
                try:
                    result = await self._reader.readuntil(END_OF_CHUNK)
                    while not result.endswith(END_MESSAGE_CHUNK):
                        result = result.rstrip(END_OF_CHUNK)
                        result += await self._reader.readuntil(END_OF_CHUNK)
                    result = result.rstrip(END_MESSAGE_CHUNK)
                except IncompleteReadError:
                    # got EOF instead of END_OF_CHUNK, usually because backend closed/broke
                    self._reader.feed_eof()
                    await self._on_disconnect()
                    continue

                logger.debug("received response.")
                try:
                    data = json.loads(result)
                except Exception as e:
                    logger.warning(f"Invalid Json {e}")
                    raise

                match data:
                    case {"type": "return", "error": error_msg, "error_type": error_type, "tool_error": True}:
                        await self._response.put((ReturnType.COMPLAINT, ErrorResponse(error_msg, error_type)))
                    case {"type": "return", "error": error_msg, "error_type": error_type}:
                        await self._response.put((ReturnType.ERROR, ErrorResponse(error_msg, error_type)))

                    case {"type": "return", "content": content}:
                        # logger.info(f'Backend: Received response with content: "{content}')
                        await self._response.put((ReturnType.SUCCESS, content))
                    case {"type": "message", "content": content}:
                        logger.info(f'Backend: - Received message with content: "{content}"')
                        for msg_queue in self.storage.sse_queues:
                            await msg_queue.put(content)
                    case _:
                        logger.error(f"Backend: - Invalid message received: {data}")
        except Exception as e:
            logger.critical("It is happening")
            logger.critical(f"{type(e)}: {e}")

    async def send_request(self, data, raise_error=True):
        logger.debug(f"try send request...{data}")
        async with self._con_lock:
            logger.debug(f"send request...{data}")
            step = 2**14
            self._writer.write(END_OF_CHUNK.join(data[chunk: chunk + step] for chunk in range(0, len(data), step)) + END_MESSAGE_CHUNK)

            try:
                result = await self._response.get()
                return_type, result = result
            except:
                breakpoint()
            match return_type:
                case ReturnType.COMPLAINT:
                    raise ConnectionManagerComplaint(*result)
                case ReturnType.ERROR:
                    raise ConnectionManagerError(*result)
                case ReturnType.CONNECTION_CLOSED:
                    logger.error("Connection closed")
                case ReturnType.SUCCESS:
                    return result
                case _:
                    logger.critical(f"Unknown return type: {return_type}")

    async def _on_disconnect(self):
        logger.warning("Connection to backend broke")
        self._writer.close()
        await self._writer.wait_closed()
        await self._response.put((ReturnType.CONNECTION_CLOSED, "Error: Connection Closed"))
        self._response = asyncio.Queue(1)
        logger.warning("Try to reconnect.....")
        await self._connect()
        logger.warning("reconnected!")

    async def close(self):
        self._writer.close()
        self._watch_task.cancel()
        await self._writer.wait_closed()
        try:
            await self._watch_task
        except asyncio.CancelledError:  # We cancelled it
            pass

        logger.info("ConnectionManager closed")
