# Entity fields

An entity has a name, a type and notes. Beside those it has fields that depend on what it is: an animal has a VHF frequency and an ear tag number, a vehicle a licence plate, a ranger a call sign. This page says which fields exist, where you fill them in and how a server admin adds more.

## The standard fields

Every server has these. A sub-type has the fields of its type: an elephant and a cow both have the Wildlife fields.

| Type | Fields |
| --- | --- |
| Wildlife | ID number, sex, birth year, age class, VHF frequency (MHz), ear tag number, breed, weight (kg) |
| Vehicles | Licence plate, brand, model, fleet number |
| People | Call sign, team |
| Infrastructure, Equipment, Environmental sensors | Asset number |

No field is required. Leave empty what you do not know.

- **VHF frequency** is for a VHF tag on the animal, beside its tracker. Type the frequency in MHz, between 30 and 1000. A comma or a point as decimal mark both work.
- **Ear tag number** is the official number of a grazing animal. It is stored in upper case without spaces and takes 4 to 20 letters and digits, such as `NL 123456789012`. Protect does not look the number up in an official register.

## Filling them in

Open an entity and choose **Edit**, on the page's header or on the **Details** card. The fields of the entity's type stand under the type. When you change the type, the fields follow.

The **Details** card on the entity's Overview shows every field that has a value. On the live map, the entity's panel shows the VHF frequency, the licence plate, the ear tag number and the call sign when they are filled in.

You need the permission to change entities (`entities:write`). A viewer reads the fields and cannot change them.

## Other

When an entity changes type, the values of fields the new type does not have are kept. They show under **Other**, in the dialog with a remove button each and on the Details card. Change the type back and the fields are there again. Values set through the API under a key no field defines show under Other as well.

## Adding fields (server admins)

Under **Server admin, Entity types**, open a type. The dialog lists the standard fields and the fields from the type above it, which cannot be changed, and below them the type's own fields.

Choose **Add a field** and give it:

- a label, such as "Collar colour";
- a kind: text, number, whole number, date, choice, or yes or no;
- for a number a unit, for a choice the choices separated by commas;
- whether it shows on the map panel, and for text whether the search finds it.

The arrows change the order. A field added to Wildlife shows for every animal; a field added to Cow shows for cows alone.

Removing a field does not remove the values the entities hold. They show under Other from then on.

A field's key is made from its label when the field is first saved and stays the same when the label changes later, since the entities hold their values under it.

## Through the API

`GET /api/v1/entity-types` answers each type with `fields`, the list in the order of the form. The values are the entity's `attributes` object, keyed by the field's key:

```json
{"vhf_frequency_mhz": 148.32, "ear_tag": "NA12345678", "sex": "female"}
```

A `PATCH` of an entity with `attributes` replaces the whole object. A value that does not fit its field answers 422 and names the field. A key no field defines is stored as it is.
