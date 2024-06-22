#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["P115Offline", "P115OfflineClearEnum"]

from asyncio import run
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from enum import Enum
from functools import partial
from hashlib import sha1
from time import time
from types import MappingProxyType
from typing import overload, Literal, Self

from asynctools import async_any, to_list
from iterutils import run_gen_step
from magnet2torrent import Magnet2Torrent # type: ignore
from undefined import undefined

from .client import check_response, P115Client
from .fs import P115Path


class P115OfflineClearEnum(Enum):
    completed = 0
    all = 1
    failed = 2
    downloading = 3
    completed_and_files = 4
    failed_and_files = 5

    @classmethod
    def ensure(cls, val, /) -> Self:
        if isinstance(val, cls):
            return val
        try:
            if isinstance(val, str):
                return cls[val]
        except KeyError:
            pass
        return cls(val)


class P115Offline:
    "离线任务列表"
    __slots__ = "client", "_sign_time", "request", "async_request"

    client: P115Client
    _sign_time: MappingProxyType

    def __init__(
        self, 
        /, 
        client: str | P115Client, 
        request: None | Callable = None, 
        async_request: None | Callable = None, 
    ):
        if isinstance(client, str):
            client = P115Client(client)
        self.client = client
        self.request = request
        self.async_request = async_request

    def __contains__(self, hash: str, /) -> bool:
        return self.has(hash)

    def __delitem__(self, hash: str, /):
        return self.remove(hash)

    def __getitem__(self, hash: str, /) -> dict:
        return self.get(hash, default=undefined)

    def __aiter__(self, /) -> AsyncIterator[dict]:
        return self.iter(async_=True)

    def __iter__(self, /) -> Iterator[dict]:
        return self.iter()

    def __len__(self, /) -> int:
        "计算共有多少个离线任务"
        return self.get_length()

    def __repr__(self, /) -> str:
        cls = type(self)
        module = cls.__module__
        name = cls.__qualname__
        if module != "__main__":
            name = module + "." + name
        return f"<{name}(client={self.client!r}) at {hex(id(self))}>"

    @property
    def download_paths_raw(self, /) -> list[dict]:
        "离线下载的目录列表"
        return self.get_download_paths_raw()

    @property
    def download_paths(self, /) -> list[P115Path]:
        "离线下载的目录列表"
        return self.get_download_paths()

    @property
    def info(self, /) -> dict:
        "获取关于离线的限制的信息"
        return self.get_info()

    @property
    def quota_info(self, /) -> dict:
        "获取当前离线配额信息（简略）"
        return self.get_quota_info()

    @property
    def quota_package_info(self, /) -> dict:
        "获取当前离线配额信息（详细）"
        return self.get_quota_package_info()

    @property
    def sign_time(self, /) -> MappingProxyType:
        "签名和时间等信息"
        try:
            sign_time = self._sign_time
            if time() - sign_time["time"] < 30 * 60:
                return sign_time
        except AttributeError:
            pass
        sign_time = self._sign_time = self.get_sign_time()
        return sign_time

    @property
    def torrent_path(self, /) -> P115Path:
        "添加 BT 种子任务的默认上传路径"
        return self.get_torrent_path()

    @overload
    def add(
        self, 
        urls: str | Iterable[str], 
        /, 
        pid: None | int = None, 
        savepath: None | str = None, 
        *, 
        async_: Literal[False] = False, 
    ) -> dict:
        ...
    @overload
    def add(
        self, 
        urls: str | Iterable[str], 
        /, 
        pid: None | int = None, 
        savepath: None | str = None, 
        *, 
        async_: Literal[True], 
    ) -> Awaitable[dict]:
        ...
    def add(
        self, 
        urls: str | Iterable[str], 
        /, 
        pid: None | int = None, 
        savepath: None | str = None, 
        *, 
        async_: Literal[False, True] = False, 
    ) -> dict | Awaitable[dict]:
        "用（1 个或若干个）链接创建离线任务"
        payload: dict
        if isinstance(urls, str):
            payload = {"url": urls}
            method = self.client.offline_add_url
        else:
            payload = {f"url[{i}]": url for i, url in enumerate(urls)}
            if not payload:
                raise ValueError("no `url` specified")
            method = self.client.offline_add_urls
        payload.update(self.sign_time)
        if pid is not None:
            payload["wp_path_id"] = pid
        if savepath:
            payload["savepath"] = savepath
        return check_response(method( # type: ignore
            payload, 
            request=self.async_request if async_ else self.request, 
            async_=async_, 
        ))

    @overload
    def add_torrent(
        self, 
        torrent_or_magnet_or_sha1_or_fid: int | bytes | str, 
        /, 
        pid: None | int = None, 
        savepath: None | str = None, 
        predicate: None | str | Callable[[dict], bool] = None, 
        *, 
        async_: Literal[False] = False, 
    ) -> dict:
        ...
    @overload
    def add_torrent(
        self, 
        torrent_or_magnet_or_sha1_or_fid: int | bytes | str, 
        /, 
        pid: None | int = None, 
        savepath: None | str = None, 
        predicate: None | str | Callable[[dict], bool] = None, 
        *, 
        async_: Literal[True], 
    ) -> Awaitable[dict]:
        ...
    def add_torrent(
        self, 
        torrent_or_magnet_or_sha1_or_fid: int | bytes | str, 
        /, 
        pid: None | int = None, 
        savepath: None | str = None, 
        predicate: None | str | Callable[[dict], bool] = None, 
        *, 
        async_: Literal[False, True] = False, 
    ) -> dict | Awaitable[dict]:
        "用 BT 种子创建离线任务"
        def gen_step():
            resp = yield partial(
                self.torrent_info, 
                torrent_or_magnet_or_sha1_or_fid, 
                async_=async_, 
            )
            if predicate is None:
                wanted = ",".join(
                    str(i) for i, info in enumerate(resp["torrent_filelist_web"])
                    if info["wanted"]
                )
            elif isinstance(predicate, str):
                wanted = predicate
            else:
                wanted = ",".join(
                    str(i) for i, info in enumerate(resp["torrent_filelist_web"]) 
                    if predicate(info)
                )
            payload = {
                "info_hash": resp["info_hash"], 
                "wanted": wanted, 
                "savepath": resp["torrent_name"] if savepath is None else savepath, 
            }
            if pid is not None:
                payload["wp_path_id"] = pid
            payload.update(self.sign_time)
            return check_response((yield partial(
                self.client.offline_add_torrent, 
                payload, 
                request=self.async_request if async_ else self.request, 
                async_=async_, 
            )))
        return run_gen_step(gen_step, async_=async_)

    @overload
    def clear(
        self, 
        /, 
        flag: int | str | P115OfflineClearEnum = P115OfflineClearEnum.all, 
        *, 
        async_: Literal[False] = False, 
    ) -> dict:
        ...
    @overload
    def clear(
        self, 
        /, 
        flag: int | str | P115OfflineClearEnum = P115OfflineClearEnum.all, 
        *, 
        async_: Literal[True], 
    ) -> Awaitable[dict]:
        ...
    def clear(
        self, 
        /, 
        flag: int | str | P115OfflineClearEnum = P115OfflineClearEnum.all, 
        *, 
        async_: Literal[False, True] = False, 
    ) -> dict | Awaitable[dict]:
        """清空离线任务列表
        :param flag: 操作目标
            - 已完成: 0, 'completed', P115OfflineClearEnum.completed
            - 全部: 1, 'all', P115OfflineClearEnum.all # 默认值
            - 已失败: 2, 'failed', P115OfflineClearEnum.failed
            - 进行中: 3, 'downloading', P115OfflineClearEnum.downloading
            - 已完成+删除源文件: 4, 'completed_and_files', P115OfflineClearEnum.completed_and_files
            - 全部+删除源文件: 5, 'failed_and_files', P115OfflineClearEnum.failed_and_files
        """
        flag = P115OfflineClearEnum(flag)
        return check_response(self.client.offline_clear( # type: ignore
            flag.value, 
            request=self.async_request if async_ else self.request, 
            async_=async_, 
        ))

    def get(
        self, 
        hash: str, 
        /, 
        default=None, 
        *, 
        async_: Literal[False, True] = False, 
    ):
        "用 infohash 查询离线任务"
        def gen_step():
            sentinel = object()
            if async_:
                ret = yield partial(
                    anext, 
                    (item async for item in self.iter(async_=True) if item["info_hash"] == hash), 
                    sentinel, 
                )
            else:
                ret = next((item for item in self.iter() if item["info_hash"] == hash), sentinel)
            if ret is not sentinel:
                return ret
            if default is undefined:
                raise LookupError(f"no such hash: {hash!r}")
            return default
        return run_gen_step(gen_step, async_=async_)

    @overload
    def get_length(
        self, 
        /, 
        async_: Literal[False] = False, 
    ) -> int:
        ...
    @overload
    def get_length(
        self, 
        /, 
        async_: Literal[True], 
    ) -> Awaitable[int]:
        ...
    def get_length(
        self, 
        /, 
        async_: Literal[False, True] = False, 
    ) -> int | Awaitable[int]:
        def gen_step():
            resp = yield partial(
                self.client.offline_list, 
                request=self.async_request if async_ else self.request, 
                async_=async_, 
            )
            return check_response(resp)["count"]
        return run_gen_step(gen_step, async_=async_)

    @overload
    def get_download_paths_raw(
        self, 
        /, 
        async_: Literal[False] = False, 
    ) -> list[dict]:
        ...
    @overload
    def get_download_paths_raw(
        self, 
        /, 
        async_: Literal[True], 
    ) -> Awaitable[list[dict]]:
        ...
    def get_download_paths_raw(
        self, 
        /, 
        async_: Literal[False, True] = False, 
    ) -> list[dict] | Awaitable[list[dict]]:
        "离线下载的目录列表"
        def gen_step():
            resp = yield partial(
                self.client.offline_download_path, 
                request=self.async_request if async_ else self.request, 
                async_=async_, 
            )
            return check_response(resp)["data"]
        return run_gen_step(gen_step, async_=async_)

    @overload
    def get_download_paths(
        self, 
        /, 
        async_: Literal[False] = False, 
    ) -> list[P115Path]:
        ...
    @overload
    def get_download_paths(
        self, 
        /, 
        async_: Literal[True], 
    ) -> Awaitable[list[P115Path]]:
        ...
    def get_download_paths(
        self, 
        /, 
        async_: Literal[False, True] = False, 
    ) -> list[P115Path] | Awaitable[list[P115Path]]:
        "离线下载的目录列表"
        as_path = self.client.get_fs(
            self.client, 
            request=self.request, 
            async_request=self.async_request, 
        ).as_path
        if async_:
            return to_list(
                await as_path(int(attr["file_id"]), async_=True) # type: ignore
                async for attr in self.get_download_paths_raw(async_=True) # type: ignore
            )
        else:
            return [as_path(int(attr["file_id"])) for attr in self.get_download_paths_raw()]

    @overload
    def get_info(
        self, 
        /, 
        async_: Literal[False] = False, 
    ) -> dict:
        ...
    @overload
    def get_info(
        self, 
        /, 
        async_: Literal[True], 
    ) -> Awaitable[dict]:
        ...
    def get_info(
        self, 
        /, 
        async_: Literal[False, True] = False, 
    ) -> dict | Awaitable[dict]:
        "获取关于离线的限制的信息"
        return check_response(self.client.offline_info( # type: ignore
            request=self.async_request if async_ else self.request, 
            async_=async_, 
        ))

    @overload
    def get_quota_info(
        self, 
        /, 
        async_: Literal[False] = False, 
    ) -> dict:
        ...
    @overload
    def get_quota_info(
        self, 
        /, 
        async_: Literal[True], 
    ) -> Awaitable[dict]:
        ...
    def get_quota_info(
        self, 
        /, 
        async_: Literal[False, True] = False, 
    ) -> dict | Awaitable[dict]:
        "获取当前离线配额信息（简略）"
        return check_response(self.client.offline_quota_info( # type: ignore
            request=self.async_request if async_ else self.request, 
            async_=async_, 
        ))

    @overload
    def get_quota_package_info(
        self, 
        /, 
        async_: Literal[False] = False, 
    ) -> dict:
        ...
    @overload
    def get_quota_package_info(
        self, 
        /, 
        async_: Literal[True], 
    ) -> Awaitable[dict]:
        ...
    def get_quota_package_info(
        self, 
        /, 
        async_: Literal[False, True] = False, 
    ) -> dict | Awaitable[dict]:
        "获取当前离线配额信息（详细）"
        return check_response(self.client.offline_quota_package_info( # type: ignore
            request=self.async_request if async_ else self.request, 
            async_=async_, 
        ))

    @overload
    def get_sign_time(
        self, 
        /, 
        async_: Literal[False] = False, 
    ) -> MappingProxyType:
        ...
    @overload
    def get_sign_time(
        self, 
        /, 
        async_: Literal[True], 
    ) -> Awaitable[MappingProxyType]:
        ...
    def get_sign_time(
        self, 
        /, 
        async_: Literal[False, True] = False, 
    ) -> MappingProxyType | Awaitable[MappingProxyType]:
        "签名和时间等信息"
        def gen_step():
            info = yield partial(self.get_info, async_=async_)
            return MappingProxyType({"sign": info["sign"], "time": info["time"]})
        return run_gen_step(gen_step, async_=async_)

    @overload
    def get_torrent_path(
        self, 
        /, 
        async_: Literal[False] = False, 
    ) -> P115Path:
        ...
    @overload
    def get_torrent_path(
        self, 
        /, 
        async_: Literal[True], 
    ) -> Awaitable[P115Path]:
        ...
    def get_torrent_path(
        self, 
        /, 
        async_: Literal[False, True] = False, 
    ) -> P115Path | Awaitable[P115Path]:
        "添加 BT 种子任务的默认上传路径"
        client = self.client
        def gen_step():
            resp = yield partial(
                client.offline_upload_torrent_path, 
                request=self.async_request if async_ else self.request, 
                async_=async_, 
            )
            as_path = client.get_fs(
                self.client, 
                request=self.request, 
                async_request=self.async_request, 
            ).as_path
            return (yield partial(
                as_path, 
                int(resp['cid']), 
                async_=async_, 
            ))
        return run_gen_step(gen_step, async_=async_)

    @overload
    def has(
        self, 
        /, 
        hash: str, 
        async_: Literal[False] = False, 
    ) -> bool:
        ...
    @overload
    def has(
        self, 
        /, 
        hash: str, 
        async_: Literal[True], 
    ) -> Awaitable[bool]:
        ...
    def has(
        self, 
        /, 
        hash: str, 
        async_: Literal[False, True] = False, 
    ) -> bool | Awaitable[bool]:
        if async_:
            return async_any(item["info_hash"] == hash async for item in self.iter(async_=True))
        else:
            return any(item["info_hash"] == hash for item in self.iter())

    @overload
    def iter(
        self, 
        /, 
        start_page: int = 1, 
        *, 
        async_: Literal[False] = False, 
    ) -> Iterator[dict]:
        ...
    @overload
    def iter(
        self, 
        /, 
        start_page: int = 1, 
        *, 
        async_: Literal[True], 
    ) -> AsyncIterator[dict]:
        ...
    def iter(
        self, 
        /, 
        start_page: int = 1, 
        *, 
        async_: Literal[False, True] = False, 
    ) -> Iterator[dict] | AsyncIterator[dict]:
        """迭代获取离线任务
        :start_page: 开始页数，从 1 开始计数，迭代从这个页数开始，到最大页数结束
        """
        if start_page < 1:
            page = 1
        else:
            page = start_page
        method = self.client.offline_list
        if async_:
            async def request():
                nonlocal page
                count = 0 
                while True:
                    resp = await check_response(method(
                        page, 
                        async_=True, 
                        request=self.async_request, 
                    ))
                    if not count:
                        count = resp["count"]
                    elif count != resp["count"]:
                        raise RuntimeError("detected count changes during iteration")
                    if not resp["tasks"]:
                        return
                    for attr in resp["tasks"]:
                        yield attr
                    if page >= resp["page_count"]:
                        return
                    page += 1
        else:
            def request():
                nonlocal page
                count = 0
                while True:
                    resp = check_response(method(page, request=self.request))
                    if not count:
                        count = resp["count"]
                    elif count != resp["count"]:
                        raise RuntimeError("detected count changes during iteration")
                    if not resp["tasks"]:
                        return
                    yield from resp["tasks"]
                    if page >= resp["page_count"]:
                        return
                    page += 1
        return request()

    @overload
    def list(
        self, 
        /, 
        page: int = 0, 
        *, 
        async_: Literal[False] = False, 
    ) -> list[dict]:
        ...
    @overload
    def list(
        self, 
        /, 
        page: int = 0, 
        *, 
        async_: Literal[True], 
    ) -> Awaitable[list[dict]]:
        ...
    def list(
        self, 
        /, 
        page: int = 0, 
        *, 
        async_: Literal[False, True] = False, 
    ) -> list[dict] | Awaitable[list[dict]]:
        """获取离线任务列表
        :param page: 获取第 `page` 页的数据，从 1 开始计数，如果小于等于 0 则返回全部
        """
        def gen_step():
            if page <= 0:
                if async_:
                    return (yield partial(to_list, self.iter(async_=True)))
                else:
                    return list(self.iter())
            resp = yield partial(
                self.client.offline_list, 
                page, 
                request=self.async_request if async_ else self.request, 
                async_=async_, 
            )
            return check_response(resp)["tasks"]
        return run_gen_step(gen_step, async_=async_)

    @overload
    def remove(
        self, 
        hashes: str | Iterable[str], 
        /, 
        remove_files: bool = False, 
        *, 
        async_: Literal[False] = False, 
    ) -> dict:
        ...
    @overload
    def remove(
        self, 
        hashes: str | Iterable[str], 
        /, 
        remove_files: bool = False, 
        *, 
        async_: Literal[True], 
    ) -> Awaitable[dict]:
        ...
    def remove(
        self, 
        hashes: str | Iterable[str], 
        /, 
        remove_files: bool = False, 
        *, 
        async_: Literal[False, True] = False, 
    ) -> dict | Awaitable[dict]:
        """用 infohash 查询并移除（1 个或若干个）离线任务
        :param hashes: （1 个或若干个）离线任务的 infohash
        :param remove_files: 移除任务时是否也删除已转存的文件
        """
        if isinstance(hashes, str):
            payload = {"hash[0]": hashes}
        else:
            payload = {f"hash[{i}]": h for i, h in enumerate(hashes)}
            if not payload:
                raise ValueError("no `hash` specified")
        if remove_files:
            payload["flag"] = "1"
        payload.update(self.sign_time)
        return check_response(self.client.offline_remove( # type: ignore
            payload, 
            request=self.async_request if async_ else self.request, 
            async_=async_, 
        ))

    @overload
    def torrent_info(
        self, 
        torrent_or_magnet_or_sha1_or_fid: int | bytes | str, 
        /, 
        async_: Literal[False] = False, 
    ) -> dict:
        ...
    @overload
    def torrent_info(
        self, 
        torrent_or_magnet_or_sha1_or_fid: int | bytes | str, 
        /, 
        async_: Literal[True], 
    ) -> Awaitable[dict]:
        ...
    def torrent_info(
        self, 
        torrent_or_magnet_or_sha1_or_fid: int | bytes | str, 
        /, 
        async_: Literal[False, True] = False, 
    ) -> dict | Awaitable[dict]:
        """获取种子的信息
        :param torrent_or_magnet_or_sha1_or_fid: BT 种子
            - bytes: 种子的二进制数据（如果种子从未被人上传过 115，就会先被上传）
            - str:
                - 磁力链接
                - 种子文件的 sha1，但要求这个种子曾被人上传到 115
            - int: 种子文件在你的网盘上的文件 id
        """
        def gen_step():
            torrent = None
            if isinstance(torrent_or_magnet_or_sha1_or_fid, int):
                fid = torrent_or_magnet_or_sha1_or_fid
                resp = yield partial(
                    self.client.fs_file, 
                    fid, 
                    request=self.async_request if async_ else self.request, 
                    async_=async_, 
                )
                sha = check_response(resp)["data"][0]["sha1"]
            elif isinstance(torrent_or_magnet_or_sha1_or_fid, bytes):
                torrent = torrent_or_magnet_or_sha1_or_fid
            elif torrent_or_magnet_or_sha1_or_fid.startswith("magnet:?xt=urn:btih:"):
                m2t = Magnet2Torrent(torrent_or_magnet_or_sha1_or_fid)
                if async_:
                    torrent = (yield m2t.retrieve_torrent)[1]
                else:
                    torrent = run(m2t.retrieve_torrent())[1]
            else:
                sha = torrent_or_magnet_or_sha1_or_fid
            if torrent is None:
                resp = check_response((yield partial(
                    self.client.offline_torrent_info, 
                    sha, 
                    request=self.async_request if async_ else self.request, 
                    async_=async_, 
                )))
            else:
                sha = sha1(torrent).hexdigest()
                try:
                    resp = check_response((yield partial(
                        self.client.offline_torrent_info, 
                        sha, 
                        request=self.async_request if async_ else self.request, 
                        async_=async_, 
                    )))
                except:
                    name = f"{sha}.torrent"
                    check_response((yield partial(
                        self.client.upload_file_sample, 
                        torrent, 
                        filename=name, 
                        request=self.async_request if async_ else self.request, 
                        async_=async_, 
                    )))
                    resp = check_response((yield partial(
                        self.client.offline_torrent_info, 
                        sha, 
                        request=self.async_request if async_ else self.request, 
                        async_=async_, 
                    )))
            resp["sha1"] = sha
            return resp
        return run_gen_step(gen_step, async_=async_)

