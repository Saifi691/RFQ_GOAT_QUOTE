"""Poll Gmail for RFQ emails and reply with the completed workbook."""
from app.mail_cli import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
