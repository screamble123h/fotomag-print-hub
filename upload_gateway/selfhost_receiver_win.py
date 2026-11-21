"""FotoMag self-host receiver: permanently poll only 127.0.0.1:19000.
Archives into existing D:\\2026\\MM\\DD\\Напрямую only after complete SHA256 and ACK checks.
Does not print/open/execute uploaded files, touch other bot channels, or delete files.
Does not create a Windows service or autorun. Safe with upload gateway disabled.
"""
import importlib.util,logging,msvcrt,os,sys,time
from pathlib import Path
from logging.handlers import RotatingFileHandler

SELF=Path(r"D:\FotoMag_Direct_Upload_Channel\selfhost_20261121")
ARCHIVE=Path(r"D:\2026")
GATEWAY="http://127.0.0.1:19000"
TOKEN=(SELF/"agent_token.txt").read_text("utf-8").strip()
assert len(TOKEN)>=48
assert ARCHIVE.is_dir() and ARCHIVE.drive.upper()=="D:"
assert GATEWAY=="http://127.0.0.1:19000"

module_path=Path(r"D:\FotoMag_Direct_Upload_Channel\production_prepared_20261121\workstation_agent.py")
assert module_path.is_file()
spec=importlib.util.spec_from_file_location("fotomag_selfhost_agent",module_path)
agent=importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)
agent.API_URL=GATEWAY
agent.TOKEN=TOKEN
agent.ARCHIVE_ROOT=ARCHIVE
agent.DATE_SUBPATH="%m/%d"
agent.INTERVAL=30
agent.validate_pc_archive(ARCHIVE)

def lock_one():
    path=SELF/"receiver.lock"
    h=path.open("a+b")
    h.seek(0)
    try:msvcrt.locking(h.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        h.close()
        raise RuntimeError("FotoMag receiver already running")
    return h

def startlog():
    logs=SELF/"logs"
    logs.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO,handlers=[
      RotatingFileHandler(logs/"receiver_selfhost.log",
         maxBytes=512000,backupCount=3,encoding="utf-8")],
      format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger("fotomag_selfhost")

def poll(logger):
    data=agent.api_request("/api/agent/orders")
    orders=data["orders"]
    if not isinstance(orders,list):raise RuntimeError("Invalid server response")
    delivered=0
    for order in orders:
        receipt=order.get("receipt","unknown")
        try:
            folder=agent.receive_order(order,ARCHIVE,pattern="%m/%d")
            logger.info("Receipt %s archived and acknowledged",receipt)
            print("FOTOMAG_RECEIVER_DELIVERED",receipt,flush=True)
            delivered+=1
        except Exception as exc:
            logger.error("Receipt %s awaiting retry (%s)",receipt,type(exc).__name__)
            print("FOTOMAG_RECEIVER_RETRY",receipt,type(exc).__name__,flush=True)
    return delivered,len(orders)

def main():
    lk=lock_one()
    logger=startlog()
    print("FOTOMAG_SELFHOST_RECEIVER_STARTED_LOOPBACK_ONLY",flush=True)
    try:
        count=0
        while True:
            try:
                delivered,pending=poll(logger)
                if count==0:
                    print("FOTOMAG_RECEIVER_INITIAL_QUEUE",pending,flush=True)
            except Exception as exc:
                logger.error("Local API temporarily unavailable: %s",type(exc).__name__)
                if count<3:print("FOTOMAG_RECEIVER_API_RETRY",type(exc).__name__,flush=True)
            count+=1
            if "--once" in sys.argv:return 0
            time.sleep(30)
    finally:
        lk.close()

if __name__=="__main__":
    sys.exit(main())
