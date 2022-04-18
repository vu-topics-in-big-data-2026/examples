Assuming you have configured the gcloud cli on your local desktop and have the command line tools configured

1. gcloud init --> configure your project and choose default region.
2. gsutil mb gs://weather_tn --> create storage bucket
3. gsutil -m cp -r weather_tn gs://weather_tn/. --> copy data to google storage bucket
4. bq mkdef --source_format=PARQUET --hive_partitioning_mode=CUSTOM --hive_partitioning_source_uri_prefix=gs://weather_tn/weather_tn/{year:INTEGER}/{month:INTEGER} gs://weather_tn/weather_tn/*.parquet > weatherdefinition.bq.txt
5. bq mk --table   --external_table_definition=weatherdefinition.bq.txt traffic.weather --> make sure you have created a dataset before. Take a look at https://cloud.google.com/bigquery/docs/datasets

Now you can follow the other bq notebook where you can run queries. Take a look at https://cloud.google.com/bigquery/docs/visualize-jupyter

Repeat the same for traffic -- your bucket where you upload traffic data may be different.

* bq mkdef --source_format=PARQUET --require_hive_partition_filter=TRUE --hive_partitioning_mode=CUSTOM --hive_partitioning_source_uri_prefix=gs://inrix_traffic/traffic_inrix_feb_2022/traffic.parquet/{county:STRING}/{year:INTEGER}/{month:INTEGER} gs://inrix_traffic/traffic_inrix_feb_2022/traffic.parquet/* > trafficdefinition.bq.txt
* bq mk --table   --external_table_definition=trafficdefinition.bq.txt  traffic.inrix
