"""

    Zoho API core functions.

"""
__copyright__ = "2010 mFabrik Research Oy"
__author__ = "Mikko Ohtamaa <mikko@mfabrik.com>"
__license__ = "GPL"
__docformat__ = "Epytext"

import urllib
import urllib.request
import urllib.parse
import logging

try:
    from xml import etree
    from xml.etree.ElementTree import Element, tostring, fromstring
except ImportError:
    try:
        from lxml import etree
        from lxml.etree import Element, tostring, fromstring
    except ImportError:
        print("XML library not available:  no etree, no lxml")
        raise

try:
    import json as simplejson
except ImportError:
    try:
        import simplejson
    except ImportError:
        # Python 2.4, no simplejson installed
        raise RuntimeError("You need json or simplejson library with your Python")

logger = logging.getLogger("Zoho API")


class ZohoException(Exception):
    """ Bad stuff happens.

    If it's level 15 or higher bug, you usually die.
    If it's lower level then you just lose all your data.

    Play some Munchkin.
    """


class Connection(object):
    """ Zoho API connector.

    Absract base class for all different Zoho API connections.
    Subclass this and override necessary methods to support different Zoho API groups.
    """

    def __init__(self, **kwargs):
        """
        @param username: manifisto@mfabrik.com

        @param password: xxxxxxx

        @param authtoken: Given by Zoho, string like 123123123-rVI20JVBveUOHIeRYWV5b5kQaMGWeIdlI$

        @param extra_auth_params: Dictionary of optional HTTP POST parameters passed to the login call

        @param auth_url: Which URL we use for authentication
        """
        options = {
            'username': None,
            'password': None,
            'authtoken': None,
            'auth_url': "https://accounts.zoho.com/login",
            'scope': None
        }
        options.update(kwargs)
        if options['username'] is not None and options['password'] is not None:
            self.username = options["username"]
            self.password = options['password']

        if options['authtoken']:
            self.authtoken = options["authtoken"]

        self.auth_url = options['auth_url']

        if options['scope'] is not None:
            self.scope = options["scope"]
        else:
            raise ZohoException("No Scope")

        # Ticket is none until the conneciton is opened
        self.ticket = None

    def get_service_name(self):
        """ Return API name which we are using. """
        raise NotImplementedError("Subclass must implement")

    def open(self):
        """ Open a new Zoho API session """
        self.ticket = self._create_ticket()

    def _create_ticket(self):
        """
        Ticket idenfities Zoho session.

        It is a bit like cookie authentication.

        @return: Ticket code
        """
        # servicename=ZohoCRM&FROM_AGENT=true&LOGIN_ID=Zoho Username or Email Address&PASSWORD=Password
        params = {
            'servicename': self.get_service_name(),
            'FROM_AGENT': 'true',
            'LOGIN_ID': self.username,
            'PASSWORD': self.password
        }

        request_url = "https://accounts.zoho.com/login"
        request = urllib.request.Request(request_url, urllib.parse.urlencode(params))
        body = urllib.request.urlopen(request).read()

        data = self._parse_ticket_response(body)

        if data["WARNING"] != "null":
            # Zoho has set an error field
            raise ZohoException("Could not auth:" + data["WARNING"])

        if data["RESULT"] != "TRUE":
            raise ZohoException("Ticket result was not valid")

        return data["TICKET"]

    def _parse_ticket_response(self, data):
        """ Dictionarize ticket opening response

        Example response::

            # #Sun Jun 27 20:10:30 PDT 2010 GETUSERNAME=null WARNING=null PASS_EXPIRY=-1 TICKET=3bc26b16d97473a1245dbf93a5dcd153 RESULT=TRUE
        """

        output = {}

        lines = data.split("\n")
        for line in lines:

            if line.startswith("#"):
                # Comment
                continue

            if line.strip() == "":
                # Empty line
                continue

            if not "=" in line:
                raise ZohoException("Bad ticket data:" + data)

            key, value = line.split("=")
            output[key] = value

        return output

    def ensure_opened(self):
        """ Make sure that the Zoho Connection is correctly opened """
        if hasattr(self, 'username') and hasattr(self, 'password') and not hasattr(self, 'authtoken'):
            if self.ticket is None:
                raise ZohoException("Need to initialize Zoho ticket first")
        else:
            return

    def do_xml_call(self, url, parameters, root):
        """  Do Zoho API call with outgoing XML payload.

        Ticket and authtoken parameters will be added automatically.

        @param url: URL to be called

        @param parameters: Optional POST parameters.

        @param root: ElementTree DOM root node to be serialized.
        """

        parameters = parameters.copy()
        parameters[self.parameter_xml] = tostring(root)
        return self.do_call(url, parameters)

    def do_call(self, url, parameters):
        """ Do Zoho API call.

        @param url: URL to be called

        @param parameters: Optional POST parameters.
        """
        # Do not mutate orginal dict
        parameters = parameters.copy()
        if self.ticket != None:
            parameters["ticket"] = self.ticket
        parameters["authtoken"] = self.authtoken
        parameters["scope"] = self.scope

        parameters = stringify(parameters)

        if logger.getEffectiveLevel() == logging.DEBUG:
            # Output Zoho API call payload
            logger.debug("Doing ZOHO API call:" + url)
            for key, value in parameters.items():
                logger.debug(key + ": " + value)
        self.parameters = parameters
        self.parameters_encoded = urllib.parse.urlencode(parameters)
        request = urllib.request.Request(url, urllib.parse.urlencode(parameters))
        response = urllib.request.urlopen(request).read()

        if logger.getEffectiveLevel() == logging.DEBUG:
            # Output Zoho API call payload
            logger.debug("ZOHO API response:" + url)
            logger.debug(response)

        return response

    def check_successful_xml(self, response):
        """ Make sure that we get "succefully" response.
        
        Throw exception of the response looks like something not liked.
        
        @raise: ZohoException if any error
        
        @return: Always True
        """

        # Example response
        # <response uri="/crm/private/xml/Leads/insertRecords"><result><message>Record(s) added successfully</message><recorddetail><FL val="Id">177376000000142007</FL><FL val="Created Time">2010-06-27 21:37:20</FL><FL val="Modified Time">2010-06-27 21:37:20</FL><FL val="Created By">Ohtamaa</FL><FL val="Modified By">Ohtamaa</FL></recorddetail></result></response>

        root = fromstring(response)

        # Check error response
        # <response uri="/crm/private/xml/Leads/insertRecords"><error><code>4401</code><message>Unable to populate data, please check if mandatory value is entered correctly.</message></error></response>
        for error in root.findall("error"):
            parameters = self.parameters
            parameters_encoded = self.parameters_encoded
            print("Got error")
            for message in error.findall("message"):
                raise ZohoException(message.text)

        return True

    def get_converted_records(self, response):
        """
        @return: Dict of ids which were converted by convert_leads
        """
        root = fromstring(response)

        record = {}
        for i in ("Contact", "Account"):
            element = root.find(i)
            record[element.get('param')] = element.text
        return record

    def get_inserted_records(self, response):
        """
        @return: List of record ids which were created by insert recoreds
        """
        root = fromstring(response)

        records = []
        for result in root.findall("result"):
            for record in result.findall("recorddetail"):
                record_detail = {}
                for fl in record.findall("FL"):
                    record_detail[fl.get("val")] = fl.text
                records.append(record_detail)
        return records


def stringify(params):
    """ Make sure all params are urllib compatible strings """
    new_dict = {}
    for key, value in params.items():
        new_dict[key] = str(value).encode()
        
    return new_dict


def decode_json(json_data):
    """ Helper function to handle Zoho specific JSON decode.

    @return: Python dictionary/list of incoming JSON data

    @raise: ZohoException if JSON'ified error message is given by Zoho
    """

    # {"response": {"uri":"/crm/private/json/Leads/getRecords","error": {"code":4500,"message":"Problem occured while processing the request"}}}
    data = simplejson.loads(json_data)

    response = data.get("response", None)
    if response:
        error = response.get("error", None)
        if error:
            raise ZohoException("Error while calling JSON Zoho api:" + str(error))

    return data
