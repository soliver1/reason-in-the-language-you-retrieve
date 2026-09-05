class MultiQueue:

    def __init__(self):
        self.queues = []

    def new_queue(self, queue):
        self.queues.append(queue)

    async def put(self, content):
        for q in self.queues:
            await q.put(content)

    def put_nowait(self, content):
        for q in self.queues:
            q.put_nowait(content)

    def remove_queue(self, queue):
        self.queues.remove(queue)



class ToolError(Exception):
    ...
