"""Resolve a Google account into a local user.

Kept as a pure function (no OAuth, no network) so it can be unit tested.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User


def resolve_google_user(db: Session, claims: dict) -> User:
    """Map Google ID-token claims to a User, creating or linking as needed.

    Branches:
      1. a user already has this google_sub -> reuse it
      2. the email is verified and a local user has it -> link (+ drop password)
      3. otherwise -> create a new passwordless user
      4. email not verified -> 400
    """
    sub = (claims.get("sub") or "").strip()
    email = (claims.get("email") or "").strip().lower()
    email_verified = bool(claims.get("email_verified"))
    name = claims.get("name")

    if not sub:
        raise HTTPException(status_code=400, detail="Google account has no subject")

    # 1. Known Google account.
    user = db.scalar(select(User).where(User.google_sub == sub))
    if user is not None:
        return user

    # 4. Refuse unverified emails before linking or creating.
    if not email_verified:
        raise HTTPException(
            status_code=400, detail="Google account email is not verified"
        )
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    # 2. Link to an existing email account. Because email signups are not
    #    verified, drop their password so a pre-registered account can't keep
    #    access to the victim's logs.
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        user.google_sub = sub
        user.password_hash = None
        if name and not user.name:
            user.name = name
        db.commit()
        db.refresh(user)
        return user

    # 3. Brand new account.
    user = User(email=email, google_sub=sub, name=name, password_hash=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
