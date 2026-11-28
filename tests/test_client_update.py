"""Mise à jour automatique du client (dernière release GitHub) : choix du fichier, empreinte, remplacement de
l'exécutable, nettoyage de l'ancien, décision de mettre à jour ou non."""
import hashlib
import io
import json
import zipfile

import pytest

from test_addon import client


def release(tag="client-v9.0.0", digest=None):
    return {"tag_name": tag, "assets": [
        {"name": "WowPlanner-Windows.zip", "browser_download_url": "https://x/win.zip", "digest": digest},
        {"name": "WowPlanner-macOS.zip", "browser_download_url": "https://x/mac.zip"},
    ]}


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buffer.getvalue()


def test_release_and_digest():
    assert client.release_asset(release(digest="sha256:ab"), "win32") == ("9.0.0", "https://x/win.zip", "sha256:ab")
    assert client.release_asset(release(), "darwin") == ("9.0.0", "https://x/mac.zip", None)
    assert client.release_asset(release(), "linux") is None
    assert client.release_asset(release(tag="v2.0"), "win32") is None  # autre chose qu'une release du client
    assert client.release_asset("garbage", "win32") is None
    data = b"contenu"
    client.check_digest(data, "sha256:" + hashlib.sha256(data).hexdigest())
    client.check_digest(data, None)  # pas d'empreinte publiée : rien à vérifier
    with pytest.raises(ValueError):
        client.check_digest(data, "sha256:" + "0" * 64)
    with pytest.raises(ValueError):
        client.check_digest(data, "md5:abc")


def test_apply_update_on_windows(tmp_path):
    target = tmp_path / "WowPlanner.exe"
    target.write_bytes(b"MZ ancien")
    new = archive({"WowPlanner/WowPlanner.exe": b"MZ nouveau", "WowPlanner/LICENSE.txt": "MIT"})
    assert client.apply_client_update(target, new, "win32") == target
    assert target.read_bytes() == b"MZ nouveau" and (tmp_path / "WowPlanner.old.exe").read_bytes() == b"MZ ancien"
    client.apply_client_update(target, archive({"WowPlanner/WowPlanner.exe": b"MZ encore"}), "win32")  # .old remplacé
    assert target.read_bytes() == b"MZ encore" and (tmp_path / "WowPlanner.old.exe").read_bytes() == b"MZ nouveau"
    for bad in (archive({"WowPlanner/LICENSE.txt": "MIT"}), archive({"WowPlanner/WowPlanner.exe": b"pas un exe"})):
        with pytest.raises(ValueError):
            client.apply_client_update(target, bad, "win32")
    assert target.read_bytes() == b"MZ encore"  # rien de touché
    client.remove_old_client(target, tries=1)
    assert not (tmp_path / "WowPlanner.old.exe").exists() and target.exists()


def test_update_decision(tmp_path, monkeypatch):
    target = tmp_path / "WowPlanner.exe"
    target.write_bytes(b"MZ ancien")
    zipped = archive({"WowPlanner/WowPlanner.exe": b"MZ nouveau"})
    digest = "sha256:" + hashlib.sha256(zipped).hexdigest()
    latest = {"tag": "client-v9.0.0"}

    def fake_fetch(url, accept="", limit=0):
        if url == client.RELEASES_API:
            return json.dumps(release(latest["tag"], digest)).encode()
        return zipped

    monkeypatch.setattr(client, "fetch", fake_fetch)
    monkeypatch.setattr(client, "sys", type("S", (), {"platform": "win32"}))
    monkeypatch.setattr(client, "frozen_target", lambda: target)
    lines, restarted = [], []
    sync = client.Sync(client.Settings(), lines.append)

    assert sync.update_client() is False  # sans fenêtre (--once) : seulement signalé, une fois
    sync.update_client()
    assert [line for line in lines if "9.0.0" in line] == [lines[0]] and target.read_bytes() == b"MZ ancien"

    sync.restart = restarted.append
    assert sync.update_client() is True
    assert restarted == [target] and target.read_bytes() == b"MZ nouveau" and "redémarrage" in lines[-1]

    latest["tag"] = f"client-v{client.VERSION}"  # déjà à jour : rien
    restarted.clear()
    assert sync.update_client() is False and restarted == []
