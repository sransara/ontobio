from ontobio.io import assocparser, gafparser, gpadparser, entityparser
from ontobio import ecomap
import click
import pandas as pd
import datetime
from ontobio.io import qc
from ontobio.io.assocparser import Report
from ontobio.model import collections


@click.command()
@click.option("--file1",
              "-file1",
              type=click.Path(),
              required=True,
              help='file1 is the source file.')
@click.option("--file2",
              "-file2",
              type=click.Path(),
              required=True,
              help='file2 is the file that is the result of a transformation.')
@click.option("--output",
              "-o",
              type=click.STRING,
              required=True,
              help='the name of the prefix for all files generated by this tool.')
@click.option("--group_by_column",
              "-gb",
              type=click.STRING,
              multiple=True,
              required=False,
              help='Options to group by include: subject, object, and/or evidence_code.'
                   'If more than one of these parameters is listed (ie: -gb = evidence_code, -gb entity_identifier, '
                   'the grouping report will group by evidence_code and entity_identifier)')
def compare_files(file1, file2, output, group_by_column):
    # decide which parser to instantiate, GAF or GPAD
    pd.set_option('display.max_rows', 35000)
    df_file1, df_file2, assocs1, assocs2 = get_parser(file1, file2)

    # get the number of counts per column of each file and summarize.
    # generate_count_report(df_file1, df_file2, file1, file2, output)

    # try to figure out how many Association objects match in each file.
    compare_associations(assocs1, assocs2, output)

    # group_by is a list of strings exactly matching column names.
    # generate_group_report(df_file1, df_file2, group_by_column, file1, file2, output)


def generate_count_report(df_file1, df_file2, file1, file2, output):
    file1_groups, counts_frame1 = get_column_count(df_file1, file1)
    file2_groups, counts_frame2 = get_column_count(df_file2, file2)

    merged_frame = pd.concat([counts_frame1, counts_frame2], axis=1)
    merged_frame.astype('Int64')
    merged_frame.to_csv(output + "_counts_per_column_report", sep='\t')
    print(merged_frame)


def generate_group_report(df_file1, df_file2, group_by_column, file1, file2, output):
    if len(group_by_column) > 0:

        s = "\n\n## GROUP BY SUMMARY \n\n"
        s += "This report generated on {}\n\n".format(datetime.date.today())
        s += "  * Group By Columns: " + str(group_by_column) + "\n"
        s += "  * Compared Files: " + file1 + ", " + file2 + "\n"
        print(s)

        for group in group_by_column:
            file1_groups, grouped_frame1 = get_group_by(df_file1, group, file1)
            file2_groups, grouped_frame2 = get_group_by(df_file2, group, file2)

            merged_group_frame = pd.concat([grouped_frame1, grouped_frame2], axis=1)
            merged_group_frame_no_nulls = merged_group_frame.fillna(0)
            fix_int_df = merged_group_frame_no_nulls.astype(int)
            fix_int_df.to_csv(output + "_" + group + "_counts_per_column_report", sep='\t')
            print("\n")
            print(fix_int_df)


def compare_associations(assocs1, assocs2, output):
    compare_report_file = open(output + "_compare_report", "w")
    processed_lines = 0

    report = Report()

    set1 = set((str(x.subject.id),
                str(x.object.id),
                #x.relation,
                x.negated,
                x.evidence.type,
                x.evidence._supporting_reference_to_str(),
                x.evidence._with_support_from_to_str()
                ) for x in assocs1 if type(x) != dict)
    difference = [x for x in assocs2 if type(x) != dict
                  if (str(x.subject.id),
                      str(x.object.id),
                      #x.relation,
                      x.negated,
                      x.evidence.type,
                      x.evidence._supporting_reference_to_str(),
                      x.evidence._with_support_from_to_str()
                      ) not in set1]
    print(difference[:1])
    failed_matches = len(difference)

    for x in difference:
        report.add_association(x)
        report.n_lines = report.n_lines + 1
        report.error(x.source_line, qc.ResultType.ERROR, "line from file1 has NO match in file2", "")

    md_report = markdown_report(report, failed_matches, processed_lines)
    print(md_report)
    compare_report_file.write(md_report)
    compare_report_file.close()

def markdown_report(report, failed_matches, processed_lines):

    json = report.to_report_json()

    s = "\n\n## DIFF SUMMARY\n\n"
    s += "This report generated on {}\n\n".format(datetime.date.today())
    s += "  * Total Unmatched Associations: {}\n".format(json["associations"])
    s += "  * Total Lines Compared: " + str(processed_lines) + "\n"
    s += "  * Total Failed matches: " + str(failed_matches) + "\n\n"

    for (rule, messages) in sorted(json["messages"].items(), key=lambda t: t[0]):
        s += "### {rule}\n\n".format(rule=rule)
        s += "* total: {amount}\n".format(amount=len(messages))
        s += "\n"
        if len(messages) > 0:
            s += "#### Messages\n\n"
        for message in messages:
            obj = " ({})".format(message["obj"]) if message["obj"] else ""
            s += "* {level} - {type}: {message}{obj} -- `{line}`\n".format(level=message["level"],
                                                                           type=message["type"],
                                                                           message=message["message"],
                                                                           line=message["line"],
                                                                           obj=obj)

        return s


def get_typed_parser(file_handle, filename):
    parser = assocparser.AssocParser()

    for line in file_handle:
        if assocparser.AssocParser().is_header(line):
            returned_parser = collections.create_parser_from_header(line, assocparser.AssocParserConfig())
            if returned_parser is not None:
                parser = returned_parser
        else:
            continue
    if isinstance(parser, gpadparser.GpadParser):
        df_file = read_gpad_csv(filename, parser.version)
    else:
        df_file = read_gaf_csv(filename, parser.version)

    return df_file, parser


def get_parser(file1, file2):

    file1_obj = assocparser.AssocParser()._ensure_file(file1)
    df_file1, parser1 = get_typed_parser(file1_obj, file1)
    file2_obj = assocparser.AssocParser()._ensure_file(file2)
    df_file2, parser2 = get_typed_parser(file2_obj, file2)

    assocs1 = parser1.parse(file1)
    assocs2 = parser2.parse(file2)

    return df_file1, df_file2, assocs1, assocs2


def read_gaf_csv(filename, version):
    ecomapping = ecomap.EcoMap()
    data_frame = pd.read_csv(filename,
                             comment='!',
                             sep='\t',
                             header=None,
                             na_filter=False,
                             names=["DB",
                                    "DB_Object_ID",
                                    "DB_Object_Symbol",
                                    "Qualifier",
                                    "GO_ID",
                                    "DB_Reference",
                                    "Evidence_code",
                                    "With_or_From",
                                    "Aspect",
                                    "DB_Object_Name",
                                    "DB_Object_Synonym",
                                    "DB_Object_Type,"
                                    "Taxon",
                                    "Date",
                                    "Assigned_By",
                                    "Annotation_Extension",
                                    "Gene_Product_Form_ID"]).fillna("")
    new_df = data_frame.filter(['DB_Object_ID', 'Qualifier', 'GO_ID', 'Evidence_code', 'DB_Reference'], axis=1)
    for eco_code in ecomapping.mappings():
        for ev in new_df['Evidence_code']:
            if eco_code[2] == ev:
                new_df['Evidence_code'] = new_df['Evidence_code'].replace([eco_code[2]],
                                                                              ecomapping.ecoclass_to_coderef(
                                                                                  eco_code[2])[0])
    return new_df


def read_gpad_csv(filename, version):
    if version.startswith("1"):
        data_frame = pd.read_csv(filename,
                                 comment='!',
                                 sep='\t',
                                 header=None,
                                 na_filter=False,
                                 names=gpad_1_2_format).fillna("")
        new_df = data_frame.filter(['subject', 'qualifiers', 'relation', 'object', 'evidence_code', 'reference'], axis=1)
    else:
        data_frame = pd.read_csv(filename,
                                 comment='!',
                                 sep='\t',
                                 header=None,
                                 na_filter=False,
                                 names=gpad_2_0_format).fillna("")
        new_df = data_frame.filter(['subject', 'negation', 'relation', 'object', 'evidence_code', 'reference'], axis=1)
    ecomapping = ecomap.EcoMap()
    for eco_code in ecomapping.mappings():
        for ev in new_df['evidence_code']:
            if eco_code[2] == ev:
                new_df['evidence_code'] = new_df['evidence_code'].replace([eco_code[2]],
                                                                          ecomapping.ecoclass_to_coderef(eco_code[2])[0])

    # normalize MGI ids
    config = assocparser.AssocParserConfig()
    config.remove_double_prefixes = True
    parser = gpadparser.GpadParser(config=config)
    for i, r in enumerate(new_df['subject']):
        r1 = parser._normalize_id(r)
        new_df.at[i, 'subject'] = r1

    return new_df


def get_group_by(data_frame, group, file):
    stats = {'filename': file, 'total_rows': data_frame.shape[0]}
    grouped_frame = data_frame.groupby(group)[group].count().to_frame()
    without_nulls = grouped_frame.fillna(0)
    return stats, without_nulls


def get_column_count(data_frame, file):
    stats = {'filename': file, 'total_rows': data_frame.shape[0]}
    count_frame = data_frame.nunique().to_frame(file)
    return stats, count_frame


gpad_1_2_format = ["DB",
                   "subject",
                   "qualifiers",
                   "object",
                   "reference",
                   "evidence_code",
                   "with_or_from",
                   "interacting_taxon",
                   "date",
                   "provided_by",
                   "annotation_extensions",
                   "properties"]

gpad_2_0_format = ["subject",
                   "negated",
                   "relation",
                   "object",
                   "reference",
                   "evidence_code",
                   "with_or_from",
                   "interacting_taxon",
                   "date",
                   "provided_by",
                   "annotation_extensions",
                   "properties"]

gaf_format = ["DB",
              "DB_Object_ID",
              "DB_Object_Symbol",
              "Qualifier",
              "GO_ID",
              "DB_Reference",
              "Evidence_code",
              "With_or_From",
              "Aspect",
              "DB_Object_Name",
              "DB_Object_Synonym",
              "DB_Object_Type",
              "Taxon",
              "Date",
              "Assigned_By",
              "Annotation_Extension",
              "Gene_Product_Form_ID"]


if __name__ == '__main__':
    compare_files()
