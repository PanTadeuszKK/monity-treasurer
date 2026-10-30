from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime, Date, Boolean, event, UniqueConstraint, CheckConstraint, Index, text, inspect
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
from pathlib import Path
from sqlalchemy.engine import URL
from paths import data_path


Base = declarative_base()

class HistoriaNaliczen(Base):
    __tablename__ = 'historia_naliczen'
    id = Column(Integer, primary_key=True)
    rok = Column(Integer, nullable=False)
    miesiac = Column(Integer, nullable=False)

class NaliczenieMiesiaca(Base):
    __tablename__ = 'naliczenia_miesiecy'
    id = Column(Integer, primary_key=True)
    rok = Column(Integer, nullable=False)
    miesiac = Column(Integer, nullable=False)
    utworzono = Column(DateTime, nullable=False, default=datetime.now)
    cofnieto = Column(DateTime, nullable=True)
    __table_args__ = (
        CheckConstraint('miesiac BETWEEN 1 AND 12'),
        Index('uq_aktywne_naliczenie', 'rok', 'miesiac', unique=True,
              sqlite_where=text('cofnieto IS NULL')),
    )


class NaliczenieCzlonka(Base):
    __tablename__ = 'naliczenia_czlonkow'
    id = Column(Integer, primary_key=True)
    naliczenie_id = Column(Integer, ForeignKey('naliczenia_miesiecy.id'), nullable=False)
    czlonek_id = Column(Integer, ForeignKey('czlonkowie.id'), nullable=False)
    kwota_grosze = Column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint('naliczenie_id', 'czlonek_id'),
        CheckConstraint('kwota_grosze > 0'),
    )


class StatusNaliczenia(Base):
    """Status z chwili naliczenia; brak wpisu oznacza nieznaną historię."""
    __tablename__ = 'statusy_naliczen'
    naliczenie_czlonka_id = Column(Integer, ForeignKey('naliczenia_czlonkow.id'), primary_key=True)
    status_id = Column(Integer, ForeignKey('statusy.id'), nullable=False)


class ZatwierdzenieStawek(Base):
    __tablename__ = 'zatwierdzenia_stawek'
    id = Column(Integer, primary_key=True)
    rok_kadencji = Column(Integer, nullable=False)
    rewizja = Column(Integer, nullable=False)
    data_decyzji = Column(Date, nullable=False)
    obowiazuje_od = Column(Date, nullable=False)
    zapisano = Column(DateTime, nullable=False, default=datetime.now)
    __table_args__ = (UniqueConstraint('rok_kadencji', 'rewizja'),)


class StawkaKadencji(Base):
    __tablename__ = 'stawki_kadencji'
    id = Column(Integer, primary_key=True)
    zatwierdzenie_id = Column(Integer, ForeignKey('zatwierdzenia_stawek.id'), nullable=False)
    status_id = Column(Integer, ForeignKey('statusy.id'), nullable=False)
    kwota_grosze = Column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint('zatwierdzenie_id', 'status_id'),
        CheckConstraint('kwota_grosze > 0'),
    )


class KorektaStawki(Base):
    __tablename__ = 'korekty_stawek'
    id = Column(Integer, primary_key=True)
    naliczenie_czlonka_id = Column(Integer, ForeignKey('naliczenia_czlonkow.id'), nullable=False)
    zatwierdzenie_id = Column(Integer, ForeignKey('zatwierdzenia_stawek.id'), nullable=False)
    roznica_grosze = Column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint('naliczenie_czlonka_id', 'zatwierdzenie_id'),
        CheckConstraint('roznica_grosze != 0'),
    )


class UzgodnienieMiesiaca(Base):
    """Powiązanie zachowanego starego wpisu z potwierdzonymi naliczeniami."""
    __tablename__ = 'uzgodnienia_miesiecy'
    historia_id = Column(Integer, ForeignKey('historia_naliczen.id'), primary_key=True)
    naliczenie_id = Column(Integer, ForeignKey('naliczenia_miesiecy.id'), nullable=False, unique=True)


class UzgodnienieHistorii(Base):
    __tablename__ = 'uzgodnienia_historii'
    id = Column(Integer, primary_key=True)
    zatwierdzenie_id = Column(Integer, ForeignKey('zatwierdzenia_stawek.id'), nullable=False)
    zapisano = Column(DateTime, nullable=False, default=datetime.now)
    dane_json = Column(String, nullable=False)


class ZmianaStatusu(Base):
    __tablename__ = 'zmiany_statusow'
    id = Column(Integer, primary_key=True)
    czlonek_id = Column(Integer, ForeignKey('czlonkowie.id'), nullable=False)
    poprzedni_status_id = Column(Integer, ForeignKey('statusy.id'), nullable=False)
    nowy_status_id = Column(Integer, ForeignKey('statusy.id'), nullable=False)
    obowiazuje_od = Column(Date, nullable=False)
    zapisano = Column(DateTime, nullable=False, default=datetime.now)


class KorektaStatusu(Base):
    __tablename__ = 'korekty_statusow'
    id = Column(Integer, primary_key=True)
    naliczenie_czlonka_id = Column(Integer, ForeignKey('naliczenia_czlonkow.id'), nullable=False)
    zmiana_statusu_id = Column(Integer, ForeignKey('zmiany_statusow.id'), nullable=False)
    roznica_grosze = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint('naliczenie_czlonka_id', 'zmiana_statusu_id'),
                      CheckConstraint('roznica_grosze != 0'))


class WysylkaEmail(Base):
    __tablename__ = 'wysylki_email'
    id = Column(Integer, primary_key=True)
    kampania = Column(String, nullable=False, index=True)
    klucz = Column(String, nullable=False, unique=True)
    czlonek_id = Column(Integer, ForeignKey('czlonkowie.id'), nullable=False)
    nadawca = Column(String, nullable=False)
    odbiorca = Column(String, nullable=False)
    temat = Column(String, nullable=False)
    tresc = Column(String, nullable=False)
    czy_html = Column(Boolean, nullable=False, default=False)
    message_id = Column(String, nullable=False, unique=True)
    tryb = Column(String, nullable=False)
    stan = Column(String, nullable=False, default='pending')
    informacja = Column(String, nullable=False, default='Oczekuje na wysłanie.')
    utworzono = Column(DateTime, nullable=False, default=datetime.now)
    aktualizacja = Column(DateTime, nullable=False, default=datetime.now)
    __table_args__ = (CheckConstraint("stan IN ('pending','sending','accepted','uncertain','not_sent','cancelled')"),)


class ImportWyciagu(Base):
    __tablename__ = 'importy_wyciagow'
    id = Column(Integer, primary_key=True)
    sha256 = Column(String, nullable=False, unique=True)
    zapisano = Column(DateTime, nullable=False, default=datetime.now)


class PozycjaWyciagu(Base):
    __tablename__ = 'pozycje_wyciagow'
    id = Column(Integer, primary_key=True)
    import_id = Column(Integer, ForeignKey('importy_wyciagow.id'), nullable=False)
    numer_wiersza = Column(Integer, nullable=False)
    odcisk = Column(String, nullable=False, index=True)
    id_bankowe = Column(String, nullable=True, unique=True)
    wplata_id = Column(Integer, ForeignKey('wplaty.id'), nullable=True, unique=True)
    dane_json = Column(String, nullable=False)
    stan = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('import_id', 'numer_wiersza'),)


class OperacjaReczna(Base):
    __tablename__ = 'operacje_reczne'
    token = Column(String, primary_key=True)
    wplata_id = Column(Integer, ForeignKey('wplaty.id'), nullable=False, unique=True)
    dane_json = Column(String, nullable=False)


class WersjaSchematu(Base):
    __tablename__ = 'wersja_schematu'
    wersja = Column(Integer, primary_key=True)
    zastosowano = Column(DateTime, nullable=False, default=datetime.now)


class Status(Base):
    __tablename__ = 'statusy'
    id = Column(Integer, primary_key=True)
    nazwa = Column(String, nullable=False)
    kwota = Column(Float, nullable=False)  # np. 35.0, 65.0

    czlonkowie = relationship("Czlonek", back_populates="status")


class Czlonek(Base):
    __tablename__ = 'czlonkowie'

    id = Column(Integer, primary_key=True)
    numer_identyfikacyjny = Column(Integer, unique=True, nullable=False)
    imie_nazwisko = Column(String, nullable=False)
    email = Column(String, nullable=True)
    bilans_otwarcia = Column(Float, default=0.0)
    aktywny = Column(Boolean, default=True)

    # Domyślnie ustawia rok i miesiąc utworzenia profilu w bazie
    rok_dolaczenia = Column(Integer, default=lambda: datetime.now().year)
    miesiac_dolaczenia = Column(Integer, default=lambda: datetime.now().month)

    # Pola wypełniane w momencie archiwizacji (usunięcia) klienta
    rok_odejscia = Column(Integer, nullable=True)
    miesiac_odejscia = Column(Integer, nullable=True)

    status_id = Column(Integer, ForeignKey('statusy.id'))
    status = relationship("Status", back_populates="czlonkowie")
    wplaty = relationship("Wplata", back_populates="czlonek", cascade="all, delete-orphan")

    konta = relationship("KontoBankowe", back_populates="czlonek", cascade="all, delete-orphan")

class KontoBankowe(Base):
    __tablename__ = 'konta_bankowe'
    numer_konta = Column(String, primary_key=True)  # Unikalny NRB
    czlonek_id = Column(Integer, ForeignKey('czlonkowie.id'))

    czlonek = relationship("Czlonek", back_populates="konta")


class Wplata(Base):
    __tablename__ = 'wplaty'
    id = Column(Integer, primary_key=True)
    czlonek_id = Column(Integer, ForeignKey('czlonkowie.id'))
    kwota = Column(Float, nullable=False)
    data_przelewu = Column(DateTime, default=datetime.now)
    tytul_oryginalny = Column(String)
    metoda_dopasowania = Column(String)
    czy_potwierdzona = Column(Boolean, default=False)

    czlonek = relationship("Czlonek", back_populates="wplaty")


class ImportCzlonkow(Base):
    __tablename__ = 'importy_czlonkow'
    sha256 = Column(String, primary_key=True)
    liczba = Column(Integer, nullable=False)
    utworzono = Column(DateTime, nullable=False, default=datetime.now)


class SaldoPoczatkoweKadencji(Base):
    __tablename__ = 'salda_poczatkowe_kadencji'
    id = Column(Integer, primary_key=True)
    czlonek_id = Column(Integer, ForeignKey('czlonkowie.id'), nullable=False, index=True)
    rok_kadencji = Column(Integer, nullable=False)
    kwota_grosze = Column(Integer, nullable=False)
    zrodlo = Column(String, nullable=False)
    utworzono = Column(DateTime, nullable=False, default=datetime.now)
    __table_args__ = (CheckConstraint('rok_kadencji BETWEEN 1900 AND 9998'),)


class Wpisowe(Base):
    __tablename__ = 'wpisowe'
    id = Column(Integer, primary_key=True)
    czlonek_id = Column(Integer, ForeignKey('czlonkowie.id'), nullable=False, unique=True)
    kwota_grosze = Column(Integer, nullable=False)
    stawka_grosze = Column(Integer, nullable=False)
    obowiazuje_od = Column(Date, nullable=False)
    zapisano = Column(DateTime, nullable=False, default=datetime.now)
    __table_args__ = (CheckConstraint('kwota_grosze > 0'),
                      CheckConstraint('kwota_grosze = 3 * stawka_grosze'))


def init_db(database_path=None):
    path = Path(database_path) if database_path is not None else data_path("monity.db")
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite", database=str(path)))

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    # Migracja 1 dodaje wyłącznie nowe tabele. Nie rekonstruuje dawnej historii.
    tables = set(inspect(engine).get_table_names())
    new_tables = {'naliczenia_miesiecy', 'naliczenia_czlonkow', 'wersja_schematu'}
    if tables and not new_tables.issubset(tables):
        from backup import backup_database
        from uuid import uuid4
        backup_database(path, path.with_name(
            f"{path.stem}.przed-migracja-1-{uuid4().hex}.db"))
    rate_tables = {'statusy_naliczen', 'zatwierdzenia_stawek', 'stawki_kadencji', 'korekty_stawek'}
    if tables and new_tables.issubset(tables) and not rate_tables.issubset(tables):
        from backup import backup_database
        from uuid import uuid4
        backup_database(path, path.with_name(
            f"{path.stem}.przed-migracja-2-{uuid4().hex}.db"))
    history_tables = {'uzgodnienia_miesiecy', 'uzgodnienia_historii'}
    if tables and new_tables.issubset(tables) and rate_tables.issubset(tables) and not history_tables.issubset(tables):
        from backup import backup_database
        from uuid import uuid4
        backup_database(path, path.with_name(
            f"{path.stem}.przed-migracja-3-{uuid4().hex}.db"))
    if tables and (new_tables | rate_tables | history_tables).issubset(tables) and not {'zmiany_statusow', 'korekty_statusow'}.issubset(tables):
        from backup import backup_database
        from uuid import uuid4
        backup_database(path, path.with_name(f"{path.stem}.przed-migracja-4-{uuid4().hex}.db"))
    previous_tables = new_tables | rate_tables | history_tables | {'zmiany_statusow', 'korekty_statusow'}
    if tables and previous_tables.issubset(tables) and not {'wysylki_email', 'importy_wyciagow', 'pozycje_wyciagow', 'operacje_reczne'}.issubset(tables):
        from backup import backup_database
        from uuid import uuid4
        backup_database(path, path.with_name(f"{path.stem}.przed-migracja-5-{uuid4().hex}.db"))
    if tables and (previous_tables | {'wysylki_email', 'importy_wyciagow', 'pozycje_wyciagow', 'operacje_reczne'}).issubset(tables) and 'salda_poczatkowe_kadencji' not in tables:
        from backup import backup_database
        from uuid import uuid4
        backup_database(path, path.with_name(f"{path.stem}.przed-migracja-6-{uuid4().hex}.db"))
    if tables and 'salda_poczatkowe_kadencji' in tables and 'importy_czlonkow' not in tables:
        from backup import backup_database
        from uuid import uuid4
        backup_database(path, path.with_name(f"{path.stem}.przed-migracja-7-{uuid4().hex}.db"))
    if tables and 'importy_czlonkow' in tables and 'wpisowe' not in tables:
        from backup import backup_database
        from uuid import uuid4
        backup_database(path, path.with_name(f"{path.stem}.przed-migracja-8-{uuid4().hex}.db"))
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT OR IGNORE INTO wersja_schematu (wersja, zastosowano) VALUES (1, CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT OR IGNORE INTO wersja_schematu (wersja, zastosowano) VALUES (2, CURRENT_TIMESTAMP)"))

        connection.execute(text("INSERT OR IGNORE INTO wersja_schematu (wersja, zastosowano) VALUES (3, CURRENT_TIMESTAMP)"))

        connection.execute(text("INSERT OR IGNORE INTO wersja_schematu (wersja, zastosowano) VALUES (4, CURRENT_TIMESTAMP)"))

        connection.execute(text("INSERT OR IGNORE INTO wersja_schematu (wersja, zastosowano) VALUES (5, CURRENT_TIMESTAMP)"))

    with engine.begin() as connection:
        connection.execute(text("INSERT OR IGNORE INTO wersja_schematu (wersja, zastosowano) VALUES (6, CURRENT_TIMESTAMP)"))

    with engine.begin() as connection:
        connection.execute(text("INSERT OR IGNORE INTO wersja_schematu (wersja, zastosowano) VALUES (7, CURRENT_TIMESTAMP)"))

    with engine.begin() as connection:
        connection.execute(text("INSERT OR IGNORE INTO wersja_schematu (wersja, zastosowano) VALUES (8, CURRENT_TIMESTAMP)"))

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    session = Session()

    if session.query(Status).count() == 0:
        standard = Status(nazwa="Standard", kwota=35.0)
        premium = Status(nazwa="Premium", kwota=65.0)
        session.add_all([standard, premium])
        session.commit()

    session.close()
    return engine

