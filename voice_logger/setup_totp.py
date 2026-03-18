"""Generate TOTP secret and display QR code for Google Authenticator setup.

Run this once to set up authentication for the Voice Logger.
The secret must be added to Vercel as the TOTP_SECRET env var.
"""

import pyotp
import sys


def main():
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)

    # Build the provisioning URI for authenticator apps
    uri = totp.provisioning_uri(
        name="Health Tracker Voice Logger",
        issuer_name="Health Tracker",
    )

    print("=" * 60)
    print("  Health Tracker Voice Logger — TOTP Setup")
    print("=" * 60)
    print()
    print("1. TOTP Secret (add to Vercel env vars as TOTP_SECRET):")
    print(f"   {secret}")
    print()
    print("2. Provisioning URI (for QR code generators):")
    print(f"   {uri}")
    print()
    print("3. To add to your authenticator app:")
    print("   - Open Google Authenticator (or Authy)")
    print("   - Tap '+' -> 'Enter setup key'")
    print("   - Account name: Health Tracker Voice Logger")
    print(f"   - Key: {secret}")
    print("   - Type: Time-based")
    print()
    print("4. Test code (current):")
    print(f"   {totp.now()}")
    print()

    # Try to generate QR code in terminal if qrcode is installed
    try:
        import qrcode
        qr = qrcode.QRCode(box_size=1, border=1)
        qr.add_data(uri)
        qr.make(fit=True)
        print("5. Scan this QR code with your authenticator app:")
        print()
        qr.print_ascii(invert=True)
    except ImportError:
        print("5. (Optional) Install 'qrcode' to display QR in terminal:")
        print("   pip install qrcode")
        print("   Then re-run this script to see a scannable QR code.")
    print()
    print("=" * 60)
    print("IMPORTANT: Save the secret above. You'll need it for Vercel.")
    print("DO NOT share this secret with anyone.")
    print("=" * 60)


if __name__ == "__main__":
    main()
