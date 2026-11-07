from django.db import models

# Create your models here.

class Sighting(models.Model):
    id = models.CharField(max_length=20, primary_key=True) 
    date = models.DateTimeField(db_index=True)
    location = models.CharField(max_length=100, db_index=True)
    species = models.CharField(max_length=100, db_index=True)
    latin_name = models.CharField(max_length=150)

    class Meta:
        ordering = ["-date", "id"] # newest sightings first, then tie-break by id

        