import uvicorn

if __name__ == '__main__':
    uvicorn.run('frontend.maintool:root_app', log_level=30, reload=True)