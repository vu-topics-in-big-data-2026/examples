from pyspark.sql import SparkSession
from pyspark import SparkContext,SparkConf
from pyspark.sql import SQLContext
from pyspark import SparkConf
from pyspark.sql import SparkSession
from pyspark.sql.functions import UserDefinedFunction,max,isnan, when, count, col, isnull,month, hour,year,minute,second,lower,to_timestamp,lit,udf,dayofweek, to_timestamp,trim
from pyspark.sql.types import TimestampType, DateType,DoubleType,FloatType,IntegerType,StringType
from pyspark.sql import DataFrame
from functools import reduce
import dateparser
import geopandas as gpd
import pandas as pd
from pyspark.ml.feature import StringIndexer, IndexToString
import os
from delta import *
import glob,sys

os.environ['SPARK_HOME']='/home/abhishek/spark-3.1.2-bin-hadoop3.2'
import findspark
from pytz import reference
findspark.init()


files='/data/disk1/carta-apc-raw/*.TXT'
filesToProcess=glob.glob(files)
output_filename='/data/disk1/carta-apc-parquet.delta'
# spark = SparkSession.builder.config('spark.executor.cores', '36').config('spark.executor.memory', '90g').config('spark.driver.memory', '40g').config('spark.driver.extraJavaOptions', '-Duser.timezone=GMT').config('spark.executor.extraJavaOptions', '-Duser.timezone=GMT').config("spark.sql.session.timeZone", "UTC").master("spark://127.0.0.1:7077").appName("new1apc").getOrCreate()

spark = SparkSession.builder.config('spark.executor.cores', '36').config('spark.executor.memory', '80g')\
        .config("spark.sql.session.timeZone", "UTC").config('spark.driver.memory', '40g').master("local[*]")\
        .appName("wego-daily").config('spark.driver.extraJavaOptions', '-Duser.timezone=UTC').config('spark.executor.extraJavaOptions', '-Duser.timezone=UTC')\
        .config("spark.sql.datetime.java8API.enabled", "true").config('spark.jars.packages', 'io.delta:delta-core_2.12:1.0.0')\
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension").config("spark.sql.execution.arrow.pyspark.enabled", "true")\
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog").config('spark.databricks.delta.retentionDurationCheck.enabled',"false").getOrCreate()
spark.conf.set("spark.sql.execution.arrow.pyspark.enabled", "true")


allgtfsfiles=spark.read.load('/home/abhishek/repos/transit-apc-processing/carta/gtfs_files/all_gtfs_files.parquet')
allstops=spark.read.load('/home/abhishek/repos/transit-apc-processing/carta/gtfs_files/all_stops.parquet')
trips= pd.read_parquet('/home/abhishek/repos/transit-apc-processing/carta/gtfs_files/all_trip_stop_times.parquet',columns=['trip_id','gtfs_file','route_id','shape_id','service_id']).drop_duplicates()
trips=spark.createDataFrame(trips) 
trips.createOrReplaceTempView("trips")

allstops=allstops.select('stop_id','stop_name','geometry','gtfs_file')
allstops=allstops.withColumn('stop_id',allstops.stop_id.cast(IntegerType()))

print(allgtfsfiles.schema)
def convertdate(x):
    try:
        out = str(x).split(" ")[0]
        return out
    except:
        return None


def convertstamp(x, y):
    try:
        out = str(y).split(" ")[0]+" "+str(x).split(" ")[1]
        return out
    except:
        return None
converttimeudf = udf(convertstamp, StringType())
convertdateudf = udf(convertdate, StringType())


sqlContext = SQLContext(spark.sparkContext)
df = spark.read.csv(
    f'{files}', inferSchema=True, header=True)
df = df.dropDuplicates(
    ['TRIP_KEY', 'SURVEY_DATE', 'ROUTE_NUMBER', 'DIRECTION_NAME', 'STOP_ID', 'SORT_ORDER'])
df = df.withColumn("TIME_SCHEDULED", converttimeudf(
    'TIME_SCHEDULED', 'SURVEY_DATE'))
df = df.withColumn("TRIP_START_TIME", converttimeudf(
    'TRIP_START_TIME', 'SURVEY_DATE'))
df = df.withColumn("TIME_ACTUAL_ARRIVE", converttimeudf(
    'TIME_ACTUAL_ARRIVE', 'SURVEY_DATE'))
df = df.withColumn("TIME_ACTUAL_DEPART", converttimeudf(
    'TIME_ACTUAL_DEPART', 'SURVEY_DATE'))
df = df.withColumn("SURVEY_DATE", convertdateudf("SURVEY_DATE"))
df=df.withColumn("TIME_SCHEDULED", to_timestamp(trim("TIME_SCHEDULED"),'M/d/yyyy H:m:s'))
df=df.withColumn("TRIP_START_TIME", to_timestamp(trim("TRIP_START_TIME"),'M/d/yyyy H:m:s'))
df=df.withColumn("TIME_ACTUAL_ARRIVE", to_timestamp(trim("TIME_ACTUAL_ARRIVE"),'M/d/yyyy H:m:s'))
df=df.withColumn("TIME_ACTUAL_DEPART", to_timestamp(trim("TIME_ACTUAL_DEPART"),'M/d/yyyy H:m:s'))
df=df.withColumn("SURVEY_DATE", to_timestamp(trim(df.SURVEY_DATE),'M/d/yyyy'))
df = df.withColumn("MONTH", month(df["SURVEY_DATE"]))
df = df.withColumn("YEAR", year(df["SURVEY_DATE"]))
df = df.withColumn('dayofweek', (dayofweek('SURVEY_DATE')+5) % 7)
df = df.withColumn('DIRECTION_NAME', when(df.DIRECTION_NAME == "OUTYBOUND", "OUTBOUND").
                when(df.DIRECTION_NAME == "0", "OUTBOUND").
                when(df.DIRECTION_NAME == "1", "INBOUND").otherwise(df.DIRECTION_NAME))
df = df.withColumn('tripstart', hour(df.TRIP_START_TIME)*3600 +
                minute(df.TRIP_START_TIME)*60+second(df.TRIP_START_TIME))
df = df.withColumnRenamed('trip_key', 'trip_id')
df = df.select([col(x).alias(x.lower()) for x in df.columns])
df = df.withColumn('delay', when(((df.timepoint == -1) & (df.time_actual_arrive.isNotNull()) & (df.time_scheduled.isNotNull())),
                                (hour(df.time_actual_arrive)*3600+minute(df.time_actual_arrive)
                                * 60+second(df.time_actual_arrive))
                                -
                                (hour(
                                    df.time_scheduled)*3600+minute(df.time_scheduled)*60+second(df.time_scheduled))

                                ))
data=df.selectExpr('cast(serial_number as int) serial_number',
    'cast(schedule_id as int) schedule_id',
    'cast(schedule_name as string)',
    'cast(signup_name as string)',
    'cast(survey_date as timestamp)',
    'cast(survey_status as int)',
    'cast(survey_type as int)',
    'cast(survey_source as int)',
    'cast(pattern_id as int)',
    'cast(route_number as string)',
    'cast(route_name as string)',
    'cast(direction_name as string)',
    'cast(branch as string)',
    'cast(service_code as string)',
    #'cast(service_type as string)',
    #'cast(service_class as string)',
    #'cast(service_mode as string)',
    'cast(trip_start_time as timestamp)',
    'cast(time_period as string)',
    'cast(service_period as string)',
    'cast(trip_number as int)',
    'cast(trip_id as string)', #need this as string
    'cast(block_number as int)',
    'cast(block_key as string)',
    'cast(block_id as int)',
    'cast(block_name as string)',
    'cast(run_number as int)',
    'cast(run_key as int)',
    'cast(vehicle_number as int)',
    'cast(vehicle_description as string)',
    'cast(vehicle_seats as int)',
    #'cast(revenue_start as string)',
    #'cast(revenue_end as string)',
    #'cast(revenue_net as string)',
    #'cast(odom_start as int)',
    #'cast(odom_end as int)',
    #'cast(odom_net  as int)',
    'cast(condition_number as int)',
    #'cast(checker_name as string)',
    'cast(garage_name as string)',
    #'cast(division_name as string)',
    'cast(operator_id as int)',
    'cast(farebox as string)',
    'cast(match_count as int)',
    'cast(comments as string)',
    'cast(sort_order as int)',
    'cast(stop_id as int)',
    'cast(main_cross_street as string)',
    'cast(travel_direction as string)',
    'cast(timepoint as int)',
    'cast(segment_miles as float)',
    'cast(time_scheduled as timestamp)',
    'cast(time_actual_arrive as timestamp)',
    'cast(time_actual_depart as timestamp)',
    'cast(dwell_time as float)',
    'cast(running_time_actual as float)',
    'cast(passengers_on as int)',
    'cast(passengers_off as int)',
    'cast(passengers_in as int)',
    'cast(passengers_spot as int)',
    'cast(wheelchairs as int)',
    'cast(bicycles as int)',
    'cast(match_distance as int)',
    'cast(timepoint_miles as float)',
    #'cast(non_student_fare as string)',
    #'cast(child as string)',
    #'cast(nr_board as int)',
    #'cast(nr_alight as int)',
    'cast(kneels as int)',
    #'cast(comment_number as string)',
    #'cast(checker_time as string) ',
    'cast(first_last_stop as int) first_last_stop',
    'cast(dayofweek as int) dayofweek',
    'cast(tripstart as int) tripstart',
    'cast(delay as int) delay',
    'cast(year as int) year',
    'cast(month as int) month')
# data.repartition(1).write.option("mapreduce.fileoutputcommitter.algorithm.version", "2").partitionBy("year","month").mode('append').format("parquet").save(f"{output_filename}")                
data=data.join(allgtfsfiles, data.signup_name== allgtfsfiles.apc_signup_name,'left')
data=data.withColumnRenamed('begin_date','gtfs_begin_date')
data=data.withColumnRenamed('real_end_date','gtfs_real_end_date')
data=data.withColumnRenamed('end_date','gtfs_end_date')
data=data.join(allstops,on=['stop_id','gtfs_file'],how='left')
data.createOrReplaceTempView("apc")
data=spark.sql('''select apc.*, trips.trip_id as gtfs_trip_id, trips.route_id as gtfs_route_id,trips.shape_id as gtfs_shape_id, trips.service_id as gtfs_service_id from apc left join trips on apc.gtfs_file=trips.gtfs_file and (instr(trips.trip_id,substr(apc.trip_id,-6))=1 or instr(trips.trip_id,substr(apc.trip_id,-6))=2)''') #we only use the last six records
columnnames=data.columns
columnnames.sort()
data=data.select(columnnames)
data.write.format("delta").partitionBy("year","month").mode('append').save(f"{output_filename}")
data=spark.read.format("delta").load(f"{output_filename}")
print(data.count()," records")
print(f'processed {files}..')
# In[ ]:
deltaTable = DeltaTable.forPath(spark, f"{output_filename}")
deltaTable.vacuum(0) 

print('done')
