"""Start the local NeuraTwin dashboard: python run.py"""
import argparse
import uvicorn

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run('neuratwin.app:app', host='127.0.0.1', port=args.port, access_log=False)
