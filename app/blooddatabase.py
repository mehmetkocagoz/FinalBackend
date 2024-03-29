from dotenv import load_dotenv
import os
import pyodbc
import json
from app.queueservice import addMessagetoQueue
from app.mailsender import sendEmailToRequestor,sendEmailToDonors
from app.donordatabase import takeDonorEmailList

load_dotenv()

server = os.getenv("AZURE_SERVER")
port = 1433
user = os.getenv("AZURE_ID")
password = os.getenv("AZURE_PASSWORD")
database = 'finaldatabase'

# Build connection string
conn_str = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server},{port};DATABASE={database};UID={user};PWD={password}"
def conn():
    try:
        # Create a connection
        with pyodbc.connect(conn_str, timeout=15) as conn:
            return conn

    except pyodbc.Error as ex:
        sqlstate = ex.args[1]
        return f"Error connecting to the database. SQLState: {sqlstate}"
    
def addBloodToDatabase(donor_name,unit):
    connection = conn()
    cursor = connection.cursor()
    
    cursor.execute("SELECT blood_type FROM Donors WHERE donor_name = ?",(donor_name,))
    blood_type = cursor.fetchone()
    blood_type = blood_type[0]

    cursor.execute("SELECT units FROM BloodDonations WHERE donor_name = ? AND blood_type = ?",(donor_name,blood_type,))
    donation = cursor.fetchone()
    
    if donation:
        donation = donation[0]
        set_unit = donation + unit
        cursor.execute("UPDATE BloodDonations SET units = ? WHERE donor_name = ?",(set_unit,donor_name,))
    else:
        cursor.execute("INSERT INTO BloodDonations (donor_name, blood_type, units) VALUES (?, ?, ?)",
                   (donor_name, blood_type, unit))
    
    connection.commit()
    connection.close()

    return "Blood Added Succesfully"


def createDonorInDatabase(donor_name, blood_type, city, town, email, phone,cdn_url):
    connection = conn()
    cursor = connection.cursor()

    # Create donor If not exists
    # Check only with email
    cursor.execute("""
                    SELECT * FROM Donors WHERE email = ?
                   """,(email,))
    donor = cursor.fetchone()
    if donor:
        connection.commit()
        connection.close()
        return "There is a Donor with same e-mail address!"
    else:
        cursor.execute("""
                INSERT INTO Donors (donor_name, blood_type, city, town, email, phone, cdn_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (donor_name, blood_type, city, town, email, phone,cdn_url,))
        connection.commit()
        connection.close()
        return "Donor Created Succesfully"

def requestBloodFromDatabase(requestor, blood_type, city, town, email, units, duration):
    req = units
    connection = conn()
    cursor = connection.cursor()
    # First we will check BloodDonations table, if there is enough blood we will directly send email to requestor 'Blood Found Donor= {'donor_name'}'
    cursor.execute("""
            SELECT SUM(units) FROM BloodDonations WHERE blood_type = ?
        """, (blood_type,))
    total_units_available = cursor.fetchone()[0] or 0
    # If there is enough available units, we will try to collect blood from donors
    # It can be one or more donors therefore I used while loop inside this if clause
    if total_units_available >= units:    
        cursor.execute("""
                    SELECT * FROM BloodDonations WHERE blood_type = ?
                       """,(blood_type,))
        donors = cursor.fetchall()
        blood_need = units
        i=0
        donor_name_list = []
        while (blood_need>0):
            don_ID = donors[i][0]
            donor_name = donors[i][1]
            blood_type = donors[i][2]
            unit = donors[i][3]
            i = i+1
            # If donor donated more then requested units of blood, we will update donor's unit and set the blood_need to 0, loop will end
            if unit > blood_need:
                unit -=blood_need
                blood_need = 0
                cursor.execute("""
                            UPDATE BloodDonations SET units = ? WHERE donation_id = ?;
                               """,(unit,don_ID,))
                donor_name_list.append(donor_name)
            # If donor donated equal request, we will delete donor row and set the blood_need to 0, loop will end
            elif unit == blood_need:
                blood_need = 0
                cursor.execute("""
                            DELETE FROM BloodDonations WHERE donation_id = ?
                               """,(don_ID,))               
                donor_name_list.append(donor_name)
            # Else we will try to collect requested blood units from donors, loop will continue
            else:
                blood_need = blood_need - unit
                cursor.execute("""
                            DELETE FROM BloodDonations WHERE donation_id = ?
                               """,(don_ID,))
                donor_name_list.append(donor_name)
        connection.commit()
    # Else there is no enough blood, we will send a message to queue, queue will handled with another service
    else:
        request_data = {
        'requestor': requestor,
        'blood_type': blood_type,
        'city': city,
        'town': town,
        'email': email,
        'units': units,
        'duration': duration
    }
        json_request = json.dumps(request_data)
        addMessagetoQueue(json_request)
        return "Not enough blood, it sends to queue"
            
    connection.commit()
    connection.close()
    message = """
        Requested Blood Found!
    """
    sendEmailToRequestor(email,message)
    donor_email_list = takeDonorEmailList(donor_name_list)
    donor_message = f"Your blood, {blood_type}, helped someone! Gifted Unit: {req}"

    sendEmailToDonors(donor_email_list,donor_message)
    return donor_name_list