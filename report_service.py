"""Raport zapisanych zdarzeń; nie udaje historycznego salda z dzisiejszej kartoteki."""
from datetime import datetime
from decimal import Decimal
from collections import defaultdict
from pathlib import Path
from tempfile import NamedTemporaryFile
import xlsxwriter
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import (Czlonek, Status, Wplata, HistoriaNaliczen, UzgodnienieMiesiaca,
    NaliczenieMiesiaca, NaliczenieCzlonka, KorektaStawki, KorektaStatusu, Wpisowe)
from annual_fees import cadence_year
from finance_service import signed_amount
from member_ledger import payment_sources

MONTHS = (6,7,8,9,10,11,12,1,2,3,4,5)


def cadence_report(session, year):
    start, end = datetime(year,6,1), datetime(year+1,6,1)
    member_rows, monthly = [], {month:{'payments':0,'charges':0} for month in MONTHS}
    with Session(bind=session.get_bind()) as operation:
        members = operation.query(Czlonek).order_by(Czlonek.imie_nazwisko,Czlonek.id).all()
        statuses = {s.id:s.nazwa for s in operation.query(Status)}
        payments = operation.query(Wplata).filter(Wplata.data_przelewu>=start,Wplata.data_przelewu<end).order_by(Wplata.data_przelewu,Wplata.id).all()
        paid = defaultdict(lambda:defaultdict(int))
        for payment in payments:
            cents = int(signed_amount(payment.kwota)*100)
            paid[payment.czlonek_id][payment.data_przelewu.month] += cents
            monthly[payment.data_przelewu.month]['payments'] += cents
        rate_delta = dict(operation.query(KorektaStawki.naliczenie_czlonka_id,func.sum(KorektaStawki.roznica_grosze)).group_by(KorektaStawki.naliczenie_czlonka_id))
        status_delta = dict(operation.query(KorektaStatusu.naliczenie_czlonka_id,func.sum(KorektaStatusu.roznica_grosze)).group_by(KorektaStatusu.naliczenie_czlonka_id))
        charges = defaultdict(int)
        charge_details = []
        for charge,batch in operation.query(NaliczenieCzlonka,NaliczenieMiesiaca).join(NaliczenieMiesiaca,NaliczenieCzlonka.naliczenie_id==NaliczenieMiesiaca.id):
            if cadence_year(batch.rok,batch.miesiac)!=year:
                continue
            correction = rate_delta.get(charge.id,0)+status_delta.get(charge.id,0)
            effective = charge.kwota_grosze+correction
            charge_details.append(dict(id=charge.id,member=charge.czlonek_id,period=f'{batch.rok}-{batch.miesiac:02}',
                original=charge.kwota_grosze,corrections=correction,effective=effective,
                reversed=batch.cofnieto.isoformat(timespec='seconds') if batch.cofnieto else '',kind='Składka miesięczna'))
            if batch.cofnieto is None:
                charges[charge.czlonek_id] += effective
                monthly[batch.miesiac]['charges'] += effective
        for fee in operation.query(Wpisowe).filter(Wpisowe.obowiazuje_od >= start.date(), Wpisowe.obowiazuje_od < end.date()):
            charges[fee.czlonek_id] += fee.kwota_grosze
            monthly[fee.obowiazuje_od.month]['charges'] += fee.kwota_grosze
            charge_details.append(dict(id=fee.id, member=fee.czlonek_id, period=f'{fee.obowiazuje_od:%Y-%m}',
                original=fee.kwota_grosze, corrections=0, effective=fee.kwota_grosze, reversed='', kind='Wpisowe'))
        unresolved = [(r.rok,r.miesiac) for r in operation.query(HistoriaNaliczen)
            if cadence_year(r.rok,r.miesiac)==year and operation.get(UzgodnienieMiesiaca,r.id) is None]
        for member in members:
            joined = member.rok_dolaczenia*12+member.miesiac_dolaczenia if member.rok_dolaczenia and member.miesiac_dolaczenia else None
            left = member.rok_odejscia*12+member.miesiac_odejscia if member.rok_odejscia and member.miesiac_odejscia else None
            overlap = (joined is None or joined<= (year+1)*12+5) and (left is None or left>=year*12+6)
            balance = int(signed_amount(member.bilans_otwarcia or 0)*100)
            if not (overlap or paid[member.id] or charges[member.id] or balance):
                continue
            unknown = [(y,m) for y,m in unresolved if (joined is None or joined<=y*12+m) and (left is None or left>=y*12+m)]
            notes = []
            if unknown:
                notes.append('Brak kwot dawnych miesięcy: '+', '.join(f'{y}-{m:02}' for y,m in unknown))
            if joined is None or (not member.aktywny and left is None):
                notes.append('Niepełne daty umowy')
            if not overlap and balance:
                notes.append('Bieżące saldo może dotyczyć wcześniejszego okresu')
            member_rows.append(dict(id=member.numer_identyfikacyjny,name=member.imie_nazwisko,
                status=statuses.get(member.status_id,'Brak'),archived=not bool(member.aktywny),
                left=f'{member.rok_odejscia}-{member.miesiac_odejscia:02}' if left else '',
                payments=tuple(paid[member.id][month] for month in MONTHS),charges=charges[member.id],
                balance=balance,note='; '.join(notes)))
        sources = payment_sources(operation, [p.id for p in payments])
        payment_details=[dict(id=p.id,member=p.czlonek_id,date=p.data_przelewu.isoformat(timespec='seconds'),
                              cents=int(signed_amount(p.kwota)*100),method=p.metoda_dopasowania or '',
                              description=p.tytul_oryginalny or '',source=sources.get(p.id, 'Brak powiązania z wyciągiem')) for p in payments]
    return dict(year=year,members=member_rows,monthly=monthly,charges=charge_details,payments=payment_details,
        warning='Należności są przypisane do miesięcy po wszystkich zapisanych korektach. '
                'Bieżące saldo nie jest saldem na koniec kadencji. Brak danych do wiarygodnego historycznego salda końcowego.')


def export_cadence(session, year, path):
    report=cadence_report(session,year)
    path=Path(path)
    if path.suffix.lower()!='.xlsx':
        raise ValueError('Raport zapisz jako XLSX.')
    with NamedTemporaryFile(dir=path.parent,suffix='.xlsx',delete=False) as temp:
        temp_path=Path(temp.name)
    try:
        with xlsxwriter.Workbook(temp_path,{'strings_to_formulas':False,'strings_to_urls':False}) as workbook:
            heading=workbook.add_format({'bold':True,'bg_color':'#142C47','font_color':'white','text_wrap':True})
            money=workbook.add_format({'num_format':'#,##0.00'})
            wrap=workbook.add_format({'text_wrap':True,'valign':'top'})
            sheet=workbook.add_worksheet('Klienci')
            headers=['ID A!','Imię i nazwisko','Bieżący status','Archiwum','Odejście']+[f'Wpłaty {m:02}' for m in MONTHS]+['Wpłaty w okresie PLN','Znane należności okresu PLN','Bieżące saldo PLN','Saldo na koniec kadencji','Uwagi']
            for col,value in enumerate(headers): sheet.write(0,col,value,heading)
            sheet.set_row(0,40)
            sheet.freeze_panes(1,2)
            sheet.set_column(0,0,8)
            sheet.set_column(1,1,28)
            sheet.set_column(2,4,15)
            sheet.set_column(5,19,16,money)
            sheet.set_column(20,21,48,wrap)
            for rownum,member in enumerate(report['members'],start=1):
                values=[member['id'],member['name'],member['status'],'Tak' if member['archived'] else 'Nie',member['left']]
                for col,value in enumerate(values): sheet.write(rownum,col,value)
                numbers=list(member['payments'])+[sum(member['payments']),member['charges'],member['balance']]
                for col,cents in enumerate(numbers,start=5): sheet.write_number(rownum,col,cents/100,money)
                sheet.write(rownum,20,'Brak wiarygodnych danych',wrap)
                sheet.write(rownum,21,member['note'],wrap)
            sheet.autofilter(0,0,max(1,len(report['members'])),len(headers)-1)
            summary=workbook.add_worksheet('Podsumowanie')
            summary.merge_range('A1:F3',report['warning'],wrap)
            for col,label in enumerate(['Miesiąc','Wpłaty PLN','Znane należności PLN']): summary.write(4,col,label,heading)
            for rownum,month in enumerate(MONTHS,start=5):
                data=report['monthly'][month]
                summary.write(rownum,0,f'{year if month>=6 else year+1}-{month:02}')
                summary.write_number(rownum,1,data['payments']/100,money)
                summary.write_number(rownum,2,data['charges']/100,money)
            summary.set_column('A:C',25)
            chart=workbook.add_chart({'type':'column'})
            for col,label,color in [(1,'Wpłaty','#18735D'),(2,'Znane należności','#416486')]:
                chart.add_series({'name':label,'categories':['Podsumowanie',5,0,16,0],
                    'values':['Podsumowanie',5,col,16,col],'fill':{'color':color}})
            chart.set_title({'name':f'Zapisane operacje kadencji {year}/{year+1}'})
            summary.insert_chart('E5',chart)
            for title,rows,headers in [('Naliczenia',report['charges'],['id','member','period','kind','original','corrections','effective','reversed']),
                                        ('Wpłaty',report['payments'],['id','member','date','cents','method','description','source'])]:
                details=workbook.add_worksheet(title)
                for col,key in enumerate(headers): details.write(0,col,key,heading)
                details.freeze_panes(1,0)
                details.set_column(0,len(headers)-1,22)
                if title == 'Wpłaty':
                    details.set_column(5,6,60,wrap)
                for rownum,data in enumerate(rows,start=1):
                    for col,key in enumerate(headers): details.write(rownum,col,data[key])
            info=workbook.add_worksheet('Informacje')
            info.set_column('A:A',110,wrap)
            info.write(0,0,f'Kadencja 01.06.{year}–31.05.{year+1}')
            info.write(1,0,report['warning'],wrap)
            info.write(3,0,'Arkusze szczegółowe zawierają kwoty w całkowitych groszach. Cofnięte naliczenia pozostają w historii i nie zwiększają sum aktywnych należności.',wrap)
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return report
