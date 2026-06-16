# -*- coding: utf-8 -*-

# Copyright (c) 2026 Oleg Polakow. All rights reserved.
# This code is licensed under Apache 2.0 with Commons Clause license (see LICENSE.md for details)

"""Built-in market presets for the live dashboard.

Each entry is ``(sector, ticker, name)``. Tickers are the numeric codes used by the
Saudi Exchange (Tadawul); Twelve Data resolves them with ``exchange="Tadawul"``.
"""

# Saudi Exchange (Tadawul) — index heavyweights first, then grouped by sector.
SAUDI_TADAWUL = [
    ("Index Heavyweights", "2222", "Saudi Aramco"),
    ("Index Heavyweights", "2010", "SABIC"),
    ("Index Heavyweights", "1180", "Saudi National Bank (SNB)"),
    ("Financials", "1120", "Al Rajhi Bank"),
    ("Financials", "1140", "Bank Albilad"),
    ("Financials", "1020", "Bank Al-Jazira"),
    ("Financials", "1150", "Alinma Bank"),
    ("Health Care", "2230", "Saudi Chemical Company Holding"),
    ("Health Care", "4163", "Al-Dawaa Medical Services"),
    ("Health Care", "4164", "Nahdi Medical"),
    ("Materials", "2020", "SABIC Agri-Nutrients"),
    ("Materials", "2310", "Sahara International Petrochemical (Sipchem)"),
    ("Materials", "2250", "Saudi Industrial Investment Group"),
    ("Materials", "2350", "Saudi Kayan Petrochemical"),
    ("Materials", "2330", "Advanced Petrochemical"),
    ("Materials", "2200", "Arabian Pipes"),
    ("Materials", "2290", "Yanbu National Petrochemical (Yansab)"),
    ("Telecom", "7010", "Saudi Telecom Company (STC)"),
    ("Telecom", "7020", "Etihad Etisalat (Mobily)"),
    ("Telecom", "4071", "Arabian Contracting Services (Al Arabia)"),
    ("Telecom", "7040", "Etihad Atheeb Telecom (GO)"),
    ("Consumer Discretionary", "1810", "Seera Group Holding"),
    ("Consumer Discretionary", "4200", "Aldrees Petroleum & Transport"),
    ("Consumer Discretionary", "4190", "Jarir Marketing"),
    ("Consumer Discretionary", "4250", "Jabal Omar Development"),
    ("Real Estate", "4325", "Umm Al Qura for Development"),
    ("Real Estate", "4321", "Arabian Centres (Cenomi Centers)"),
    ("Real Estate", "4322", "Retal Urban Development"),
    ("Real Estate", "4300", "Dar Al Arkan Real Estate"),
    ("Consumer Staples", "2280", "Almarai"),
    ("Consumer Staples", "4290", "Al Khaleej Training & Education"),
    ("Consumer Staples", "6010", "National Agricultural Development (NADEC)"),
    ("Industrials", "2120", "Saudi Advanced Industries"),
    ("Industrials", "4031", "Saudi Ground Services"),
    ("Industrials", "4264", "Flynas"),
    ("Industrials", "2040", "Saudi Ceramic"),
    ("Industrials", "2320", "Al Babtain Power & Telecom"),
    ("Industrials", "2370", "Middle East Specialized Cables (MESC)"),
    ("Industrials", "2240", "Zamil Industrial Investment"),
    ("Industrials", "1303", "Electrical Industries"),
    ("Industrials", "4030", "National Shipping Company (Bahri)"),
    ("Energy", "2223", "Saudi Aramco Base Oil (Luberef)"),
    ("Utilities", "2083", "Power & Water Utility for Jubail & Yanbu (Marafiq)"),
]
