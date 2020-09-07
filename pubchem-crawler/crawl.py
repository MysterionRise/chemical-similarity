import argparse
import ftplib
import gzip
import logging
import os
import time
from pathlib import Path
from typing import Callable, Generator, Iterable, List, Set

import indigo
from ftpretty import ftpretty
from indigo.bingo import Bingo


class FTP:
    def __init__(self, *args, **kwargs):
        self.conn = ftpretty(*args, **kwargs)

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.conn.close()
        except Exception as e:
            logging.error(e)


class PubchemLoader:

    dir_mapping = {"compounds": "Compound"}

    # Order make sense
    sup_extensions = [".md5", ".gz"]

    def __init__(self, data: str, target_dir: str, fmt: str) -> None:
        self.ftp = "ftp.ncbi.nlm.nih.gov"
        self.target = Path("pubchem") / self.dir_mapping[data]
        self.fmt = fmt.upper()
        self.target_dir = Path(target_dir)

    def __checksum(self, target_file: Path) -> bool:
        # todo: create checksum functionality
        target_file.with_suffix(".gz.md5").is_file()
        return True

    def __download_file(self, ftp_: ftpretty, filename: Path, tries: int = 0):
        pth = self.target_dir / filename
        if pth.suffix not in self.sup_extensions:
            return
        try:
            pth.parent.mkdir(parents=True)
        except FileExistsError:
            pass
        try:
            with open(pth, "xb") as target_file:
                ftp_.get(filename, target_file)
                logging.info("Downloaded %s", pth)
        except FileExistsError:
            if pth.suffix == ".md5":
                # always reload md5 files
                pth.unlink()
                self.__download_file(ftp_, filename, tries + 1)
            elif not self.__checksum(pth):
                self.__download_file(ftp_, filename, tries + 1)
            else:
                logging.error("File %s already downloaded", filename)

    @staticmethod
    def get_names(dir_: Iterable) -> Set[str]:
        return set([Path(name).name for name in dir_])

    def __diff(
        self, source_dir: str, source_file_list: List[str], ext_: str
    ) -> Generator[Path, None, None]:
        pth = self.target_dir / source_dir
        targets = self.get_names(pth.glob(f"*.{ext_}"))
        sources = set(
            filter(
                lambda x: Path(x).suffix == f".{ext_}",
                self.get_names(source_file_list),
            )
        )
        diff_names = sources - targets

        if diff_names:
            ftp_dir = Path(source_file_list[0]).parent
            for name in diff_names:
                yield ftp_dir / name

    def full_download(self):
        source_dir = f"{self.target}/CURRENT-Full/{self.fmt}"

        with FTP(self.ftp, "anonymous", "anonymous@domain.com") as ftp_:
            for ext_ in self.sup_extensions:
                for remote_file in self.__diff(
                    source_dir, ftp_.list(source_dir), ext_[1:]
                ):
                    try:
                        logging.info("start download %s", remote_file)
                        self.__download_file(ftp_, remote_file)
                    except (ftplib.error_temp, EOFError, BaseException) as err_:
                        logging.warning("%s, sleeping 5 seconds", err_)
                        time.sleep(5)
                        logging.warning("retry...")
                        self.full_download()


class Extractor:
    def __init__(self, chembl_dir):
        self.chembl_dir = Path(chembl_dir)

    @staticmethod
    def __gunzip_content(file: Path) -> Path:
        target_file = file.with_suffix("")
        with open(target_file, "wb") as target, gzip.open(file, "rb") as src:
            target.write(src.read())
        return target_file

    @staticmethod
    def cast_path(root: Path, files: List[str]) -> Generator[Path, None, None]:
        for file in files:
            yield root / file

    def extract(self, handler: Callable[[Path], None]):
        for root, dirs, files in os.walk(self.chembl_dir):
            for file in self.cast_path(Path(root), files):
                if file.suffix == ".gz":
                    try:
                        extracted = self.__gunzip_content(file)
                        handler(extracted)
                        extracted.unlink(missing_ok=True)
                    except EOFError as err_:
                        logging.error("File %s: %s", file, err_)


class BingoNoSQLDatabase:
    def __init__(self, arg_ns: argparse.Namespace):
        self.arg_ns = arg_ns
        self.session = indigo.Indigo()

        if arg_ns.bingo_dir:
            self.bingo_dir = arg_ns.bingo_dir
        else:
            self.bingo_dir = Path(arg_ns.pubchem_dir) / "bingo_dir"

        if self.bingo_dir.is_dir():
            self.bingo_conn = Bingo.loadDatabaseFile(
                self.session, str(self.bingo_dir), ""
            )
        else:
            self.bingo_conn = Bingo.createDatabaseFile(
                self.session, str(self.bingo_dir), "molecule", ""
            )

    def handler(self, source_file: Path):
        for molecule in self.session.iterateSDFile(str(source_file)):
            try:
                self.bingo_conn.insert(molecule)
            except indigo.bingo.BingoException as e:
                logging.error("Cannot upload molecule: %s", e)


class ElasticDatabase:
    def __init__(self, arg_ns: argparse.Namespace):
        pass

    def handler(self, source_file: Path):
        pass


def download(arg_ns: argparse.Namespace) -> None:
    loader = PubchemLoader("compounds", arg_ns.pubchem_dir, "sdf")
    loader.full_download()


def extract(arg_ns: argparse.Namespace) -> None:
    extractor = Extractor(arg_ns.pubchem_dir)
    if arg_ns.database == "bingo_nosql":
        extractor.extract(BingoNoSQLDatabase(arg_ns).handler)


if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Pubchem crawler")

    subparsers = parser.add_subparsers(help="select mode: download, extract")

    parser_download = subparsers.add_parser("download")
    parser_download.set_defaults(func=download)
    parser_download.add_argument(
        "--pubchem-dir",
        type=str,
        default="./pubchem_dir",
        help="Pubchem directory path",
    )

    parser_extract = subparsers.add_parser("extract")
    parser_extract.add_argument("--database", type=str, default="bingo_nosql")
    parser_extract.add_argument(
        "--pubchem-dir",
        type=str,
        default="./pubchem_dir",
        help="Pubchem directory path",
    )
    parser_extract.add_argument(
        "--bingo-dir", type=str, help="Bingo nosql db location"
    )
    parser_extract.set_defaults(func=extract)

    args = parser.parse_args()
    args.func(args)
