Source: https://developers.lexware.io/docs/#invoices-endpoint-create-an-invoice
# Create an Invoice

`POST {resourceurl}/v1/invoices[?finalize=true]`

Invoices transmitted via the API are created in draft mode per default. To create a finalized invoice with status *open* the optional query parameter `finalize` has to be set. 
The status of an invoice cannot be changed via the api.

The created invoice will be shown in the main voucher list in Lexware: https://app.lexware.de/vouchers.

The contents of the invoice are expected in the request's body as an application/json and must not contain read-only fields. See https://developers.lexware.io/docs/#faq-texts-in-sales-vouchers on further information on text fields.

Description of required properties when creating an invoice.

|           Property | Required | Notes                                                                                                                                                                                                 |
|-------------------:|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|        voucherDate | Yes      |                                                                                                                                                                                                       |
|            address | Yes      | Nested object. Required fields for address please see below.                                                                                                                                          |
|          lineItems | Yes      | List of nested objects. Required fields for lineItems please see below.                                                                                                                               |
|         totalPrice | Yes      | Nested object. Required fields for totalPrice please see below.                                                                                                                                       |
|      taxConditions | Yes      | Nested object. Required fields for taxConditions see below.                                                                                                                                           |
| shippingConditions | Yes      | Nested object. Required fields for shippingConditions please see below.                                                                                                                               |

## Sample request to create an invoice

```shell
curl https://api.lexware.io/v1/invoices
-X POST
-H "Authorization: Bearer {accessToken}"
-H "Content-Type: application/json"
-H "Accept: application/json"
-d '
{
 "archived": false,
  "voucherDate": "2023-02-22T00:00:00.000+01:00",
   "address": {
   "name": "Bike & Ride GmbH & Co. KG",
    "supplement": "Gebäude 10",
    "street": "Musterstraße 42",
    "city": "Freiburg",
    "zip": "79112",
    "countryCode": "DE"
  },
  "lineItems": [
    {
      "type": "custom",
      "name": "Energieriegel Testpaket",
      "quantity": 1,
      "unitName": "Stück",
      "unitPrice": {
        "currency": "EUR",
        "netAmount": 5,
        "taxRatePercentage": 0
      },
      "discountPercentage": 0
    },
    {
      "type": "text",
      "name": "Strukturieren Sie Ihre Belege durch Text-Elemente.",
      "description": "Das hilft beim Verständnis"
    }
  ],
  "totalPrice": {
    "currency": "EUR"
   },
  "taxConditions": {
    "taxType": "net"
  },
  "paymentConditions": {
    "paymentTermLabel": "10 Tage - 3 %, 30 Tage netto",
    "paymentTermDuration": 30,
    "paymentDiscountConditions": {
      "discountPercentage": 3,
      "discountRange": 10
    }
  },
  "shippingConditions": {
    "shippingDate": "2023-04-22T00:00:00.000+02:00",
    "shippingType": "delivery"
  },
  "title": "Rechnung",
  "introduction": "Ihre bestellten Positionen stellen wir Ihnen hiermit in Rechnung",
  "remark": "Vielen Dank für Ihren Einkauf"
}
'
```

## Sample response
```json
{
  "id": "e9066f04-8cc7-4616-93f8-ac9ecc8479c8",
  "resourceUri": "https://api.lexware.io/v1/invoices/66196c43-bfee-baf3-4335-d610367059db",
  "createdDate": "2023-06-29T15:15:09.447+02:00",
  "updatedDate": "2023-06-29T15:15:09.447+02:00",
  "version": 1
}
```
