from django import forms


class PackageForm(forms.Form):
    package_name = forms.CharField(label="Package Name", max_length=255)
    package_version = forms.CharField(label="Package Version", max_length=255, required=False)


