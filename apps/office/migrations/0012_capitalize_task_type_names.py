from django.db import migrations


def capitalize_words(value):
    translations = str.maketrans({"i": "İ", "ı": "I"})
    return "".join(
        char.translate(translations).upper()
        if char.isalpha() and (index == 0 or not value[index - 1].isalpha())
        else char
        for index, char in enumerate(value)
    )


def update_names(apps, schema_editor):
    task_type = apps.get_model("office", "TaskType")
    records = list(task_type.objects.all())
    names = [capitalize_words(item.name) for item in records]
    if len(names) != len(set(names)):
        raise ValueError("Görev türleri aynı ada dönüşüyor; adlar kontrol edilmeden değiştirilemez.")
    for item, name in zip(records, names):
        if item.name != name:
            task_type.objects.filter(pk=item.pk).update(name=name)


class Migration(migrations.Migration):
    dependencies = [("office", "0011_tasktype_category_data")]
    operations = [migrations.RunPython(update_names, migrations.RunPython.noop)]
