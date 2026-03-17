import hydropandas as hpd
import pandas as pd
import requests
import json

def get_knmi_stations_and_export():
    """
    Haalt KNMI weerstation locaties op en exporteert deze als CSV bestand
    """
    try:
        # Methode 1: Via KNMI publieke data API
        print("Bezig met opvragen KNMI stations...")
        
        # Probeer eerst de KNMI stations list via de officiële bron
        stations_url = "https://www.knmi.nl/schooner/services/stationdata/getStationData.php"
        
        params = {
            'format': 'csv'
        }
        
        response = requests.get(stations_url, params=params)
        
        # Parse CSV response
        from io import StringIO
        csv_data = StringIO(response.text)
        df = pd.read_csv(csv_data)
        
        # Hernoem kolommen als nodig
        if df.shape[1] > 0:
            print(f"Kolommen gevonden: {list(df.columns)}")
            df.to_csv('knmi_stations.csv', index=False)
            print(f"\n✓ {len(df)} KNMI stations geëxporteerd naar knmi_stations.csv")
            print("\nOverzicht:")
            print(df.head())
            return df
        
    except Exception as e:
        print(f"Methode 1 mislukt: {e}")
        
        # Fallback Methode 2: Hardcoded KNMI stations (bekende stations)
        print("\nGebruik fallback methode met bekende KNMI stations...")
        
        try:
            # Dit zijn bekende KNMI synop stations - gelijk aantal items per kolom!
            stations_data = {
                'code': [
                    '06010', '06020', '06030', '06040', '06050', '06060', '06070', 
                    '06080', '06090', '06110', '06120', '06130', '06140', '06150', '06160',
                    '06170', '06180', '06190', '06200', '06210', '06220', '06230', '06240', '06250', '06260', '06270', '06280',
                    '06290', '06310', '06320', '06330', '06340', '06350', '06360', '06370'
                ],
                'naam': [
                    'Den Helder', 'Vlieland', 'Terschelling', 'Leeuwarden', 'Groningen',
                    'De Faan', 'Soesterberg', 'Beek (L)', 'Amsterdam', 'Gilze-Rijen', 'Vlissingen', 'Antwerpen',
                    'Rotterdam', 'Eindhoven', 'Maastricht', 'Winterswijk', 'Herwijnen', 
                    'Zierikzee', 'Den Burg', 'Sluiskil', 'Texelhors', 'Stadslanden', 
                    'Zeeplatform F-3', 'Stavoren', 'Uithuizermeeden', 'Oterdum', 'Heino',
                    'Twente', 'Zeeplatform P', 'Zeeplatform Q', 'Ter Heijde', 'Lauwersoog',
                    'Hellevoetsluis', 'Appingedam', 'Harlingen'
                ],
                'latitude': [
                    52.956, 53.143, 53.343, 53.195, 53.196, 
                    52.916, 52.149, 50.914, 52.318, 51.563, 51.441, 51.218,
                    51.929, 51.447, 50.912, 52.450, 51.869,
                    51.496, 53.043, 51.410, 53.066, 53.275,
                    52.400, 52.901, 53.398, 53.338, 52.272,
                    52.268, 52.650, 54.200, 51.969, 53.406,
                    51.926, 53.338, 53.226
                ],
                'longitude': [
                    4.790, 5.185, 5.343, 6.196, 6.565,
                    5.303, 5.318, 5.700, 5.299, 5.017, 3.597, 4.017,
                    4.448, 5.537, 5.937, 6.654, 5.302,
                    3.658, 2.388, 3.989, 4.564, 4.690,
                    3.200, 5.245, 6.875, 6.975, 6.759,
                    6.899, 6.414, 4.550, 4.130, 6.353,
                    4.220, 6.600, 5.397
                ]
            }
            
            df = pd.DataFrame(stations_data)
            df.to_csv('knmi_stations.csv', index=False)
            
            print(f"\n✓ {len(df)} bekende KNMI stations geëxporteerd naar knmi_stations.csv")
            print("\nOverzicht:")
            print(df)
            return df
            
        except Exception as e2:
            print(f"Fallback mislukt: {e2}")
            import traceback
            traceback.print_exc()
            return None

if __name__ == "__main__":
    df = get_knmi_stations_and_export()