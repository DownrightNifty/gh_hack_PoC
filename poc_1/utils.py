import gpsoauth
import httpx

def gpsoauth_perform_oauth(email, master_token, android_id, service, app,
                           client_sig, device_country='us',
                           operatorCountry='us', lang='en', sdk_version=17,
                           proxy=None):
    """
    Same as gpsoauth.perform_oauth(), but we also ask for the account ID. An
    "accountId" field should be returned in response.
    """

    # directly copied from gpsoauth source code
    data = {
        'accountType': 'HOSTED_OR_GOOGLE',
        'Email':   email,
        'has_permission':  1,
        'EncryptedPasswd': master_token,
        'service': service,
        'source':  'android',
        'androidId':   android_id,
        'app': app,
        'client_sig': client_sig,
        'device_country':  device_country,
        'operatorCountry': device_country,
        'lang':    lang,
        'sdk_version': sdk_version
    }

    # add "get_accountid"
    data['get_accountid'] = 1

    return gpsoauth._perform_auth_request(data, proxy)

def httpx_rm_headers(headers_list):
    """
    Returns an httpx event hook that removes the provided headers from requests.
    """
    def hook(request):
        for header in headers_list:
            del request.headers[header]
    return hook

def httpx_raise_on_err(err_class):
    """
    Returns an httpx event hook that raises the provided Exception class on any
    response error.
    """
    def hook(response):
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise err_class(f'Server returned {response.status_code}: '
                            f'{response.url}') from None
    return hook